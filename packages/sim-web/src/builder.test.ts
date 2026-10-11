import { readFileSync } from "node:fs";
import type { Design } from "strandbeest-core";
import { describe, expect, it } from "vitest";
import { buildMjcf, resolveSpec } from "./builder";
import { scenarioFromDesign } from "./from-design";
import { obstaclesXml, terrainPlan } from "./terrains";

interface Case {
	name: string;
	design: string;
	overrides: Record<string, unknown>;
	expected:
		| { error: string }
		| {
				xml: string;
				n_legs: number;
				crank_joint: string;
				crank_q0: number;
				actuator: string;
				hip_height: number;
				bar_mass_total: number;
				plan: {
					slope_deg: number;
					softness: number[] | null;
					obstacles: number;
				};
		  };
}
const corpus = JSON.parse(
	readFileSync(
		new URL("../../../contracts/sim-mjcf/cases.json", import.meta.url),
		"utf8",
	),
) as { tolerance: number; designs: Record<string, Design>; cases: Case[] };

const close = (a: number, b: number, tol: number) =>
	Math.abs(a - b) <= tol * Math.max(1, Math.abs(b));

function build(c: Case) {
	const cfg = scenarioFromDesign(
		corpus.designs[c.design] as Design,
		structuredClone(c.overrides),
	);
	const plan = terrainPlan(cfg);
	return {
		plan,
		built: buildMjcf(cfg, resolveSpec(cfg), obstaclesXml(plan.obstacles)),
	};
}

// contracts/sim-mjcf is written by the Python builder; the browser builder must reproduce it exactly (ADR-0009: duplicated module)
describe("MJCF builder matches the Python builder", () => {
	it("the corpus is not empty and covers the shared scenes", () => {
		expect(corpus.cases.length).toBeGreaterThan(30);
		expect(corpus.cases.filter((c) => c.name.startsWith("scene-")).length).toBe(
			10,
		);
	});

	for (const c of corpus.cases) {
		it(c.name, () => {
			if ("error" in c.expected) {
				expect(() => build(c)).toThrow();
				return;
			}
			const { plan, built } = build(c);
			const e = c.expected;
			expect(built.xml).toBe(e.xml);
			expect(built.n_legs).toBe(e.n_legs);
			expect(built.crank_joint).toBe(e.crank_joint);
			expect(built.actuator).toBe(e.actuator);
			for (const k of ["crank_q0", "hip_height", "bar_mass_total"] as const)
				expect(close(built[k], e[k], corpus.tolerance), k).toBe(true);
			expect(plan.slopeDeg).toBe(e.plan.slope_deg);
			expect(plan.softness).toEqual(e.plan.softness);
			expect(plan.obstacles.length).toBe(e.plan.obstacles);
		});
	}
});
