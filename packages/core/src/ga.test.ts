import { describe, expect, it } from "vitest";
import { fitnessFlatStroke, paramsToGenome } from "./fitness";
import { runGA } from "./ga";
import { JANSEN_LENGTHS } from "./jansen";
import { createRng } from "./rng";

describe("rng", () => {
	it("is deterministic per seed", () => {
		const a = createRng(7);
		const b = createRng(7);
		expect([a(), a(), a()]).toEqual([b(), b(), b()]);
	});
});

describe("GA", () => {
	const start = paramsToGenome(JANSEN_LENGTHS);
	const opts = { seed: 1, population: 24, generations: 8 };

	it("scores the original Jansen legs as valid", () => {
		expect(Number.isFinite(fitnessFlatStroke(start))).toBe(true);
	});

	it("never does worse than its starting genome (elitism)", () => {
		const r = runGA(start, fitnessFlatStroke, opts);
		expect(r.bestFitness).toBeGreaterThanOrEqual(fitnessFlatStroke(start));
	});

	it("is reproducible for a fixed seed", () => {
		const a = runGA(start, fitnessFlatStroke, opts);
		const b = runGA(start, fitnessFlatStroke, opts);
		expect(a.best).toEqual(b.best);
	});
});

describe("fitness sanity", () => {
	it("rejects legs whose foot rises above the hip", () => {
		const g = paramsToGenome(JANSEN_LENGTHS);
		g[7] = 1; // collapse link h: foot can no longer reach the ground sensibly
		expect(fitnessFlatStroke(g)).toBe(Number.NEGATIVE_INFINITY);
	});
});
