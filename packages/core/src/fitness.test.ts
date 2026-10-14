import { describe, expect, it } from "vitest";
import cases from "../../../contracts/fitness/cases.json";
import {
	fitnessFlatStroke,
	fitnessHighStep,
	fitnessSpeed,
	INFEASIBLE,
	infeasibility,
} from "./fitness";
import { genomeSpace } from "./genome";
import { jansenSpec } from "./jansen";
import { trace } from "./linkage";

// Jansen's topology; assembles at all 24 probe angles but not at every one of the 90 trace samples (Q-06)
const gap = (
	cases as { cases: { genome: number[]; infeasibility: number }[] }
).cases.filter((c) => c.infeasibility === -5.05);

describe("a leg whose trace is empty (assembles at the probes, not at every sample)", () => {
	const space = genomeSpace(jansenSpec());

	it("is in the corpus", () => {
		expect(gap.length).toBeGreaterThanOrEqual(3);
	});

	it("really has an empty trace", () => {
		for (const c of gap)
			expect(trace(space.toSpec(c.genome), 90).assembled).toBe(false);
	});

	it("gets one finite infeasible penalty from every fitness function, never NaN", () => {
		for (const c of gap) {
			expect(infeasibility(space, c.genome)).toBe(-5.05);
			for (const f of [
				fitnessFlatStroke(space),
				fitnessHighStep(space),
				fitnessSpeed(space),
			]) {
				const v = f(c.genome);
				expect(Number.isNaN(v)).toBe(false);
				expect(v).toBe(-5.05);
				expect(v).toBeLessThanOrEqual(INFEASIBLE);
			}
		}
	});
});
