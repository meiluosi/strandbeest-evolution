import { readFileSync } from "node:fs";
import loadMujoco from "@mujoco/mujoco";
import type { Design } from "strandbeest-core";
import { beforeAll, describe, expect, it } from "vitest";
import type { AuditObservationDocument } from "./audit-observation";
import type { Diagnosis } from "./events";
import { scenarioFromDesign } from "./from-design";
import { gaitWindow, RunCancelled, runPreview } from "./run";

const repo = (p: string) => new URL(`../../../${p}`, import.meta.url);
const corpus = JSON.parse(
	readFileSync(repo("contracts/sim-run/cases-contact-v3.json"), "utf8"),
) as {
	cases: {
		name: string;
		design: string;
		overrides: Record<string, unknown>;
		expected: Expected;
	}[];
};
const observations = JSON.parse(
	readFileSync(repo("contracts/sim-run/observation-v3.json"), "utf8"),
) as {
	cases: {
		name: string;
		metrics: Expected["metrics"];
		diagnosis: Expected["diagnosis"];
		audit_observation: AuditObservationDocument;
	}[];
};

function observationExpected(name: string) {
	const found = observations.cases.find((c) => c.name === name);
	if (!found) throw new Error(`Missing all-step observation fixture: ${name}`);
	return found;
}

function nearObservation(
	got: AuditObservationDocument | undefined,
	expected: AuditObservationDocument,
) {
	expect(got).toBeDefined();
	for (const key of Object.keys(
		expected,
	) as (keyof AuditObservationDocument)[]) {
		if (key === "max_loop_residual_m" || key === "max_penetration_m")
			near(got![key], expected[key], `observation.${key}`, 1e-7);
		else expect(got![key], `observation.${key}`).toEqual(expected[key]);
	}
}
interface Expected {
	series: Record<"t" | "psi" | "x" | "torque", number[]>;
	frames: Record<
		| "t"
		| "pos"
		| "quat"
		| "foot_pos"
		| "foot_force"
		| "foot_slip"
		| "com"
		| "contact",
		unknown[]
	> | null;
	events: unknown[];
	diagnosis: unknown[];
	energy: Record<string, number[]>;
	scene: {
		bodies: string[];
		geoms: {
			name: string;
			type: string;
			body: number;
			foot: boolean;
			radius?: number;
			a?: number[];
			b?: number[];
		}[];
		obstacles: unknown[];
		slope_deg: number;
	} | null;
	metrics: Record<string, number | boolean | null>;
	stalled: boolean;
}

// flatten nested arrays to numbers and report the largest |a - b|, so a failure says how far off the browser run is
const flat = (a: unknown): number[] =>
	Array.isArray(a) ? a.flatMap(flat) : [a as number];
function maxDiff(got: unknown, want: unknown): number {
	const g = flat(got);
	const w = flat(want);
	if (g.length !== w.length) return Number.POSITIVE_INFINITY;
	return g.reduce((m, v, i) => Math.max(m, Math.abs(v - (w[i] as number))), 0);
}

// deep comparison with a relative tolerance for numbers (events, diagnosis evidence, metrics)
const near = (a: unknown, b: unknown, path: string, tol = 1e-9): void => {
	if (typeof b === "number" && typeof a === "number")
		expect(Math.abs(a - b), path).toBeLessThanOrEqual(
			tol * Math.max(1, Math.abs(b)),
		);
	else if (Array.isArray(b)) {
		expect(Array.isArray(a), path).toBe(true);
		expect((a as unknown[]).length, path).toBe(b.length);
		b.forEach((v, i) => near((a as unknown[])[i], v, `${path}[${i}]`, tol));
	} else if (b && typeof b === "object") {
		expect(Object.keys(a as object).sort(), path).toEqual(
			Object.keys(b).sort(),
		);
		for (const k of Object.keys(b))
			near(
				(a as Record<string, unknown>)[k],
				(b as Record<string, unknown>)[k],
				`${path}.${k}`,
				tol,
			);
	} else expect(a, path).toEqual(b);
};

type Metrics = Expected["metrics"];
function nearMetrics(a: Metrics, b: Metrics, stalled: boolean) {
	const turnsA = a.energy_window_revs as number;
	const turnsB = b.energy_window_revs as number;
	// In a stalled trace, dividing by ~1e-4 turns or ~1e-7 J amplifies
	// roundoff. Compare the underlying displacement/work for these ratios:
	// 0.1 nm, 1 pJ and 0.1 nrad absolute bounds, without changing G1 gates.
	const tinyWindow =
		stalled && turnsA > 0 && turnsB > 0 && Math.max(turnsA, turnsB) < 1e-3;
	const inputA = turnsA * (a.energy_in_per_rev as number);
	const inputB = turnsB * (b.energy_in_per_rev as number);
	if (tinyWindow) {
		expect(
			Math.abs(turnsA - turnsB) * 2 * Math.PI,
			"stalled crank angle",
		).toBeLessThanOrEqual(1e-10);
		expect(Math.abs(inputA - inputB), "stalled input work").toBeLessThanOrEqual(
			1e-12,
		);
	}
	for (const key of Object.keys(b)) {
		if (tinyWindow && key === "stride_per_rev") {
			expect(
				Math.abs((a[key] as number) * turnsA - (b[key] as number) * turnsB),
				key,
			).toBeLessThanOrEqual(1e-10);
		} else if (
			tinyWindow &&
			/^energy_(contact|loops|friction|residual)_share$/.test(key)
		) {
			expect(
				Math.abs((a[key] as number) * inputA - (b[key] as number) * inputB),
				key,
			).toBeLessThanOrEqual(1e-12);
		} else near(a[key], b[key], `metrics.${key}`, 1e-7);
	}
}

function comparableDiagnosis(
	rows: unknown[],
	metrics: Metrics,
	stalled: boolean,
) {
	const turns = metrics.energy_window_revs as number;
	const stride = metrics.stride_per_rev as number;
	if (
		!stalled ||
		!(turns > 0 && turns < 1e-3) ||
		!Number.isFinite(stride) ||
		!stride
	)
		return rows;
	// The displacement represented by stride was checked separately above.
	// Check that diagnostic efficiency still applies the same nominal stride,
	// without reintroducing division by the almost-zero crank travel.
	return rows.map((row) => {
		const diagnosis = row as Diagnosis;
		const efficiency = diagnosis.evidence.advance_efficiency;
		if (typeof efficiency !== "number") return diagnosis;
		return {
			...diagnosis,
			evidence: {
				...diagnosis.evidence,
				advance_efficiency: efficiency / stride,
			},
		};
	});
}

it("stalled diagnostic comparison rejects an incorrect efficiency", () => {
	const metrics = { energy_window_revs: 1e-4, stride_per_rev: 0.28 };
	const expected = [
		{ code: "torque_limit_too_low", evidence: { advance_efficiency: 1.0 } },
	];
	const changed = [
		{ code: "torque_limit_too_low", evidence: { advance_efficiency: 1.001 } },
	];
	expect(() =>
		near(
			comparableDiagnosis(changed, metrics, true),
			comparableDiagnosis(expected, metrics, true),
			"diagnosis",
			1e-7,
		),
	).toThrow();
});

it.each(["displacement", "work"])(
	"stalled metric comparison rejects a physical %s error",
	(kind) => {
		const reference = {
			energy_window_revs: 1e-4,
			energy_in_per_rev: 0.0025,
			stride_per_rev: 0.28,
			energy_loops_share: 1.5,
		};
		const changed = { ...reference };
		if (kind === "displacement")
			changed.stride_per_rev += 1e-8 / reference.energy_window_revs;
		else
			changed.energy_loops_share +=
				1e-10 / (reference.energy_window_revs * reference.energy_in_per_rev);
		expect(() => nearMetrics(changed, reference, true)).toThrow();
	},
);

let mj: Awaited<ReturnType<typeof loadMujoco>>;
beforeAll(async () => {
	mj = await loadMujoco();
});

it("preserves absorbed work and the native energy balance for original G1 case 11", {
	timeout: 120_000,
}, async () => {
	const fixture = JSON.parse(
		readFileSync(repo("contracts/sim-run/signed-energy-v3.json"), "utf8"),
	);
	const replay = await runPreview(
		mj,
		scenarioFromDesign(fixture.design, structuredClone(fixture.overrides)),
		{ yieldMs: 1e9 },
	);
	expect(replay.metrics.energy_in_per_rev).toBeLessThan(0);
	expect(Math.abs(replay.metrics.energy_residual_share as number)).toBeLessThan(
		0.02,
	);
	const current = observationExpected("signed-energy");
	nearMetrics(replay.metrics, current.metrics, false);
	nearObservation(replay.audit_observation, current.audit_observation);
	for (const key of ["t", "psi", "x", "torque"] as const)
		expect(
			maxDiff(replay.series[key], fixture.replay.series[key]),
			key,
		).toBeLessThan(6e-6);
	for (const [key, values] of Object.entries(fixture.replay.energy))
		expect(maxDiff(replay.energy![key], values), key).toBeLessThan(1.5e-7);
});

// Contact-v3 corrects damping; energy-v2 keeps aligned t_n observations. Earlier corpora remain unchanged.
// The same MJCF and step order must give the Python trajectory across the pinned native/WASM versions. Replays are rounded
// (4 decimals for poses, 3 for forces, 5 for the series), so the allowed difference is half a unit of the last decimal.
describe("browser preview follows the Python run (contracts/sim-run)", () => {
	for (const c of corpus.cases) {
		it(c.name, { timeout: 120_000 }, async () => {
			const design = JSON.parse(readFileSync(repo(c.design), "utf8")) as Design;
			const rep = await runPreview(
				mj,
				scenarioFromDesign(design, structuredClone(c.overrides)),
				{ yieldMs: 1e9 },
			);
			const current = observationExpected(c.name);
			const e = {
				...c.expected,
				metrics: current.metrics,
				diagnosis: current.diagnosis,
			};
			nearObservation(rep.audit_observation, current.audit_observation);
			expect(rep.audit).toBeDefined();
			expect(rep.audit?.version).toBe(2);
			expect(rep.audit?.physical_validation_implied).toBe(false);
			expect(rep.audit?.passed).toBe(false);
			expect(
				rep.audit?.findings.some(
					(f) =>
						f.check === "audit_evidence" &&
						f.evidence.metric === "audit_observation",
				),
			).toBe(false);
			const half = (d: number) => 0.5 * 10 ** -d + 1e-6; // + float32 slack: Python frames are float32
			// the replay keeps at most about 500 samples of the crank series, as the API does (len // 500)
			const step = Math.max(1, Math.floor(e.series.t.length / 500));
			const dec = (v: number[]) => v.filter((_, i) => i % step === 0);
			const want = {
				t: dec(e.series.t),
				psi: dec(e.series.psi),
				x: dec(e.series.x),
				torque: dec(e.series.torque),
			};
			expect(rep.series.t.length).toBe(want.t.length);
			expect(maxDiff(rep.series.t, want.t)).toBeLessThan(half(5));
			expect(maxDiff(rep.series.psi, want.psi)).toBeLessThan(half(5));
			expect(maxDiff(rep.series.x, want.x)).toBeLessThan(half(5));
			expect(maxDiff(rep.series.torque, want.torque)).toBeLessThan(half(5));
			const fr = e.frames;
			if (fr) {
				expect(rep.t.length).toBe(fr.t.length);
				expect(maxDiff(rep.t, fr.t)).toBeLessThan(half(4));
				expect(maxDiff(rep.pos, fr.pos)).toBeLessThan(half(4));
				expect(maxDiff(rep.quat, fr.quat)).toBeLessThan(half(4));
				expect(rep.contact).toEqual(fr.contact);
				expect(maxDiff(rep.foot_pos, fr.foot_pos)).toBeLessThan(half(4));
				expect(maxDiff(rep.foot_force, fr.foot_force)).toBeLessThan(half(3));
				expect(maxDiff(rep.foot_slip, fr.foot_slip)).toBeLessThan(half(4));
				expect(maxDiff(rep.com, fr.com)).toBeLessThan(half(4));
			}
			// the audit: metrics (including the energy account), events, diagnosis and the energy panel's series
			expect(Object.keys(rep.metrics).sort()).toEqual(
				Object.keys(e.metrics).sort(),
			);
			nearMetrics(rep.metrics, e.metrics, rep.stalled && e.stalled);
			near(rep.events, e.events, "events");
			near(
				comparableDiagnosis(
					rep.diagnosis,
					rep.metrics,
					rep.stalled && e.stalled,
				),
				comparableDiagnosis(e.diagnosis, e.metrics, rep.stalled && e.stalled),
				"diagnosis",
				1e-7,
			);
			expect(Object.keys(rep.energy ?? {}).sort()).toEqual(
				Object.keys(e.energy).sort(),
			);
			for (const [k, want] of Object.entries(e.energy))
				expect(
					maxDiff((rep.energy as Record<string, number[]>)[k], want),
					`energy.${k}`,
				).toBeLessThan(1.5e-7);
			expect(rep.stalled).toBe(e.stalled);
			const sc = e.scene; // Python writes a scene only for runs with frames
			if (sc) {
				expect(rep.scene.bodies).toEqual(sc.bodies);
				expect(rep.scene.geoms.length).toBe(sc.geoms.length);
				expect(rep.scene.obstacles.length).toBe(sc.obstacles.length);
				expect(rep.scene.slope_deg).toBeCloseTo(sc.slope_deg, 12);
				expect(rep.scene.geoms.filter((g) => g.foot).length).toBe(
					sc.geoms.filter((g) => g.foot).length,
				);
				sc.geoms.forEach((g, i) => {
					const got = rep.scene.geoms[i] as (typeof rep.scene.geoms)[number];
					expect(got.type).toBe(g.type);
					expect(got.name).toBe(g.name);
					if (g.a) expect(maxDiff(got.a, g.a)).toBeLessThan(1e-4);
					if (g.b) expect(maxDiff(got.b, g.b)).toBeLessThan(1e-4);
				});
			}
		});
	}

	it("the contact cases really exercise contacts and the blocked step", () => {
		const step = corpus.cases.find((c) => c.name === "step")
			?.expected as Expected;
		const flat = corpus.cases.find((c) => c.name === "flat")
			?.expected as Expected;
		const down = (e: Expected) =>
			Math.max(
				...(
					(e.frames as NonNullable<Expected["frames"]>).contact as number[][]
				).map((r) => r.reduce((a, b) => a + b, 0)),
			);
		expect(down(flat)).toBeGreaterThanOrEqual(2);
		expect(down(step)).toBeGreaterThanOrEqual(down(flat));
		expect(
			(step.scene as NonNullable<Expected["scene"]>).obstacles.length,
		).toBe(1);
	});
});

describe("run control", () => {
	it("refuses a drive it does not know", async () => {
		const design = JSON.parse(
			readFileSync(
				repo("schemas/examples/design-jansen-small-6leg.json"),
				"utf8",
			),
		) as Design;
		await expect(
			runPreview(
				mj,
				scenarioFromDesign(design, { drive: { kind: "flywheel" } }),
			),
		).rejects.toThrow(/motor and sail drives/);
	});

	it("stops when cancelled and reports progress", {
		timeout: 60_000,
	}, async () => {
		const design = JSON.parse(
			readFileSync(
				repo("schemas/examples/design-jansen-small-6leg.json"),
				"utf8",
			),
		) as Design;
		let ticks = 0;
		let last = 0;
		const p = runPreview(
			mj,
			scenarioFromDesign(design, { run: { revolutions: 2 } }),
			{
				yieldMs: 0,
				onProgress: (x) => {
					ticks++;
					last = x.simTime;
				},
				cancelled: () => ticks >= 3,
			},
		);
		await expect(p).rejects.toBeInstanceOf(RunCancelled);
		expect(ticks).toBeGreaterThanOrEqual(3);
		expect(last).toBeLessThan(5);
	});
});

describe("gaitWindow", () => {
	it("uses everything for a run shorter than two revolutions and flags it", () => {
		const t = [0, 1, 2, 3];
		const psi = [0, 1, 2, 3];
		const g = gaitWindow(t, psi, [0, 0.1, 0.2, 0.3], [1, 2, 3, 2]);
		expect(g.steady_window).toBe(0);
		expect(g.mean_speed).toBeCloseTo(0.1, 12);
		expect(g.peak_torque).toBe(3);
		expect(g.torque_ptp).toBe(2);
	});

	it("skips the first revolution when there are two or more", () => {
		const rev = 2 * Math.PI;
		const psi = Array.from({ length: 41 }, (_, i) => (i / 40) * 3 * rev);
		const x = psi.map((p) => p / rev); // 1 m per revolution
		const g = gaitWindow(
			psi.map((_, i) => i),
			psi,
			x,
			psi.map(() => 1),
		);
		expect(g.steady_window).toBe(1);
		expect(g.stride_per_rev).toBeCloseTo(1, 9);
	});
});
