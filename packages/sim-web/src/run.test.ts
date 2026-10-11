import { readFileSync } from "node:fs";
import loadMujoco from "@mujoco/mujoco";
import type { Design } from "strandbeest-core";
import { beforeAll, describe, expect, it } from "vitest";
import { scenarioFromDesign } from "./from-design";
import { gaitWindow, RunCancelled, runPreview } from "./run";

const repo = (p: string) => new URL(`../../../${p}`, import.meta.url);
const corpus = JSON.parse(
	readFileSync(repo("contracts/sim-run/cases.json"), "utf8"),
) as {
	cases: {
		name: string;
		design: string;
		overrides: Record<string, unknown>;
		expected: Expected;
	}[];
};
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

let mj: Awaited<ReturnType<typeof loadMujoco>>;
beforeAll(async () => {
	mj = await loadMujoco();
});

// The same MJCF, the same engine version (3.14.0) and the same step order must give the Python trajectory. Replays are rounded
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
			const e = c.expected;
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
			// a walker stalled at its torque limit turns the crank by 0.0015 rad: 1e-11 of divergence between wasm and native (the free
			// runs agree to 1e-16) becomes 1e-8 in stride_per_rev, which divides by that angle
			near(rep.metrics, e.metrics, "metrics", 1e-7);
			near(rep.events, e.events, "events");
			near(rep.diagnosis, e.diagnosis, "diagnosis", 1e-7);
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
	it("refuses a sail drive in the preview", async () => {
		const design = JSON.parse(
			readFileSync(
				repo("schemas/examples/design-jansen-small-6leg.json"),
				"utf8",
			),
		) as Design;
		await expect(
			runPreview(mj, scenarioFromDesign(design, { drive: { kind: "sail" } })),
		).rejects.toThrow(/motor drive/);
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
