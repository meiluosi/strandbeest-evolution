import { describe, expect, it } from "vitest";
import { fitnessFlatStroke, INFEASIBLE } from "./fitness";
import { runGA } from "./ga";
import { JANSEN_SPACE } from "./genome";
import { createRng } from "./rng";

describe("rng", () => {
	it("is deterministic per seed", () => {
		const a = createRng(7);
		const b = createRng(7);
		expect([a(), a(), a()]).toEqual([b(), b(), b()]);
	});
});

describe("GA", () => {
	const start = JANSEN_SPACE.toGenome();
	const flat = fitnessFlatStroke(JANSEN_SPACE);
	const opts = { seed: 1, population: 24, generations: 8 };

	it("scores the original Jansen legs as valid", () => {
		expect(Number.isFinite(flat(start))).toBe(true);
	});

	it("never does worse than its starting genome (elitism)", () => {
		const r = runGA(start, flat, opts);
		expect(r.bestFitness).toBeGreaterThanOrEqual(flat(start));
	});

	it("is reproducible for a fixed seed", () => {
		const a = runGA(start, flat, opts);
		const b = runGA(start, flat, opts);
		expect(a.best).toEqual(b.best);
	});
});

describe("fitness sanity", () => {
	it("rejects legs whose foot rises above the hip", () => {
		const g = JANSEN_SPACE.toGenome();
		g[7] = 1; // collapse link h: foot can no longer reach the ground sensibly
		expect(fitnessFlatStroke(JANSEN_SPACE)(g)).toBeLessThanOrEqual(INFEASIBLE);
	});
});

describe("golden run (guards refactors of the fitness/genome code: E3-01 moved them to GenomeSpace unchanged)", () => {
	it("flat-stroke GA from Jansen's lengths, seed 1, 80 x 25, gives the recorded result", () => {
		// recorded 2026-10-06 with the code from before the GenomeSpace refactor (0.6469557486851051); the refactor reproduced it bit for bit.
		// Re-recorded 2026-10-15 (Q-06): a leg that assembles at the probes but not at every trace sample no longer scores NaN but -5.05.
		const r = runGA(JANSEN_SPACE.toGenome(), fitnessFlatStroke(JANSEN_SPACE), {
			seed: 1,
			population: 80,
			generations: 25,
		});
		expect(r.bestFitness).toBeCloseTo(0.6776223287613968, 12);
		expect(r.best.slice(0, 4)).toEqual([
			43.11465820766656, 40.83226668567402, 37.394963188048635,
			40.87346286896109,
		]);
	});
});
