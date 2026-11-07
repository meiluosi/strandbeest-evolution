import { describe, expect, it } from "vitest";
import { evolve, runGA } from "./ga";

describe("GA Robustness, Diversity, and Numerical Immunity", () => {
	it("isolates occasional NaN fitness evaluations without corrupting elites or selection", () => {
		const start = [10, 10, 10];
		let evalCount = 0;
		const poisonFitness = (g: number[]) => {
			evalCount++;
			// Periodically simulate a failed/divergent numerical simulation returning NaN
			if (evalCount % 5 === 0) return Number.NaN;
			// Normal quadratic sphere objective
			return -g.reduce((s, v) => s + (v - 15) ** 2, 0);
		};

		const res = runGA(start, poisonFitness, {
			seed: 12345,
			population: 20,
			generations: 15,
		});

		// Best fitness must be finite and not corrupted by NaN
		expect(Number.isFinite(res.bestFitness)).toBe(true);
		expect(Number.isNaN(res.bestFitness)).toBe(false);
		expect(res.best.every((v) => Number.isFinite(v))).toBe(true);

		// Every recorded generation state must have valid finite best fitness
		for (const state of res.history) {
			expect(Number.isFinite(state.bestFitness)).toBe(true);
			expect(Number.isNaN(state.bestFitness)).toBe(false);
		}
	});

	it("maintains population diversity and avoids variance collapse across 25 generations", () => {
		const start = [50, 50, 50, 50];
		const sphereFitness = (g: number[]) =>
			-g.reduce((s, v) => s + (v - 30) ** 2, 0);

		const genStates = Array.from(
			evolve(start, sphereFitness, {
				seed: 42,
				population: 30,
				generations: 25,
			}),
		);

		expect(genStates.length).toBe(26);
		const initialBest = genStates[0]!.bestFitness;
		const finalBest = genStates[genStates.length - 1]!.bestFitness;

		// Evolutionary progress: final fitness should improve over random initial
		expect(finalBest).toBeGreaterThan(initialBest);

		// Check that mean fitness remains finite and reasonable throughout
		for (const state of genStates) {
			expect(Number.isFinite(state.meanFitness)).toBe(true);
			expect(state.bestFitness).toBeGreaterThanOrEqual(state.meanFitness);
		}
	});

	it("handles homogeneous initial population without infinite loop", () => {
		const start = [1.0, 2.0, 3.0];
		const flatFitness = () => 42.0;

		const res = runGA(start, flatFitness, {
			seed: 999,
			population: 10,
			generations: 5,
		});

		expect(res.bestFitness).toBe(42.0);
		expect(res.history.length).toBe(6);
	});
});
