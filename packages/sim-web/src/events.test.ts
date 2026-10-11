import { readFileSync } from "node:fs";
import type { Design } from "strandbeest-core";
import { describe, expect, it } from "vitest";
import { simConfig } from "./config";
import {
	type Diagnosis,
	detectEvents,
	diagnose,
	energyMetrics,
	nominalStrideM,
	type RunEvent,
	type RunResult,
} from "./events";
import { pyFixed, pyPercent0 } from "./pyfmt";

const repo = (p: string) => new URL(`../../../${p}`, import.meta.url);
interface Case {
	name: string;
	design: string;
	config: Record<string, unknown>;
	result: RunResult;
	expected: {
		events: RunEvent[];
		diagnosis: Diagnosis[];
		nominal_stride_m: number | null;
	};
}
const corpus = JSON.parse(
	readFileSync(repo("contracts/sim-events/cases.json"), "utf8"),
) as { cases: Case[] };

const near = (a: unknown, b: unknown, path: string): void => {
	if (typeof b === "number" && typeof a === "number")
		expect(Math.abs(a - b), path).toBeLessThanOrEqual(
			1e-12 * Math.max(1, Math.abs(b)),
		);
	else if (Array.isArray(b)) {
		expect(Array.isArray(a), path).toBe(true);
		expect((a as unknown[]).length, path).toBe(b.length);
		b.forEach((v, i) => near((a as unknown[])[i], v, `${path}[${i}]`));
	} else if (b && typeof b === "object") {
		expect(Object.keys(a as object).sort(), path).toEqual(
			Object.keys(b).sort(),
		);
		for (const k of Object.keys(b))
			near(
				(a as Record<string, unknown>)[k],
				(b as Record<string, unknown>)[k],
				`${path}.${k}`,
			);
	} else expect(a, path).toEqual(b);
};

// The rules (events.py) must give the same events, the same diagnosis code, severity, English text and evidence numbers as Python.
describe("events and diagnosis match the Python rules (contracts/sim-events)", () => {
	it("the corpus fires every rule", () => {
		const codes = new Set(
			corpus.cases.flatMap((c) => c.expected.diagnosis.map((d) => d.code)),
		);
		for (const code of [
			"ok",
			"slipping",
			"deep_sinkage",
			"slow_unexplained",
			"loop_constraints_opened",
			"torque_limit_too_low",
			"blocked_by_terrain_torque_limit",
			"sail_torque_insufficient",
			"sail_weak",
		])
			expect(codes.has(code), code).toBe(true);
		const kinds = new Set(
			corpus.cases.flatMap((c) => c.expected.events.map((e) => e.kind)),
		);
		for (const kind of [
			"start",
			"stall",
			"touchdown",
			"liftoff",
			"slip",
			"torque_limit",
			"loop_open",
			"gust",
		])
			expect(kinds.has(kind), kind).toBe(true);
	});

	for (const c of corpus.cases) {
		it(c.name, () => {
			const sc = simConfig(c.config);
			const design = JSON.parse(readFileSync(repo(c.design), "utf8")) as Design;
			const nominal = nominalStrideM(sc, design.linkage as never);
			near(nominal, c.expected.nominal_stride_m, "nominal_stride_m");
			const events = detectEvents(c.result, sc);
			near(events, c.expected.events, "events");
			near(
				diagnose(c.result, events, sc, nominal),
				c.expected.diagnosis,
				"diagnosis",
			);
		});
	}
});

describe("python-style number formatting used in the messages", () => {
	it("rounds exact ties to even like Python", () => {
		expect(pyFixed(0.125, 2)).toBe("0.12");
		expect(pyFixed(0.375, 2)).toBe("0.38");
		expect(pyFixed(2.5, 0)).toBe("2");
		expect(pyFixed(3.5, 0)).toBe("4");
		expect(pyFixed(1.005, 2)).toBe("1.00");
		expect(pyFixed(-0.125, 2)).toBe("-0.12");
		expect(pyPercent0(0.125)).toBe("12%");
		expect(pyPercent0(0.5)).toBe("50%");
		expect(pyPercent0(0.855)).toBe("86%"); // 85.5 -> 86 (even), as CPython gives
		expect(pyPercent0(0.635)).toBe("64%");
		expect(pyPercent0(0.285)).toBe("28%"); // 28.499999999999996: not a tie
	});
});

describe("energyMetrics", () => {
	const rev = 2 * Math.PI;
	// 3 revolutions at constant power: 2 J per revolution in, 1.5 J into contact, 0.5 J into the loops, nothing stored
	const n = 61;
	const psi = Array.from({ length: n }, (_, i) => (i / (n - 1)) * 3 * rev);
	const ramp = (perRev: number) => psi.map((p) => (p / rev) * perRev);
	it("closes the account over whole revolutions after the first", () => {
		const m = energyMetrics(psi, {
			e_in: ramp(2),
			e_contact: ramp(1.5),
			e_loops: ramp(0.5),
			e_friction: ramp(0),
			kinetic: psi.map(() => 0.1),
			potential: psi.map(() => 0.2),
		});
		expect(m.energy_in_per_rev).toBeCloseTo(2, 9);
		expect(m.energy_contact_share).toBeCloseTo(0.75, 9);
		expect(m.energy_loops_share).toBeCloseTo(0.25, 9);
		expect(m.energy_residual_share).toBeCloseTo(0, 9);
		expect(m.energy_window_revs).toBeCloseTo(2, 9);
	});
	it("returns only the window for a run that puts in no energy, and nothing for too few samples", () => {
		const zero = psi.map(() => 0);
		expect(
			Object.keys(
				energyMetrics(psi, {
					e_in: zero,
					e_contact: zero,
					e_loops: zero,
					e_friction: zero,
					kinetic: zero,
					potential: zero,
				}),
			),
		).toEqual(["energy_window_revs"]);
		expect(
			energyMetrics([0], {
				e_in: [0],
				e_contact: [0],
				e_loops: [0],
				e_friction: [0],
				kinetic: [0],
				potential: [0],
			}),
		).toEqual({});
	});
});
