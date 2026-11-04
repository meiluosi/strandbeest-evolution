import { readFileSync } from "node:fs";
import loadMujoco from "@mujoco/mujoco";
import type { Design } from "strandbeest-core";
import { beforeAll, expect, it } from "vitest";
import { scenarioFromDesign } from "./from-design";
import { runPreview } from "./run";

const repo = (path: string) => new URL(`../../../${path}`, import.meta.url);
const fixture = JSON.parse(
	readFileSync(repo("contracts/audit-reference/phase.json"), "utf8"),
) as {
	design: string;
	cases: {
		direction: number;
		overrides: Record<string, unknown>;
		theta_rad: number[];
		psi_rad: number[];
		t_s: number[];
		stalled: boolean;
	}[];
};
let mj: Awaited<ReturnType<typeof loadMujoco>>;
beforeAll(async () => {
	mj = await loadMujoco();
});

it.each(fixture.cases)(
	"absolute phase matches native observation for direction $direction",
	{ timeout: 30_000 },
	async (row) => {
		const design = JSON.parse(
			readFileSync(repo(fixture.design), "utf8"),
		) as Design;
		const replay = await runPreview(
			mj,
			scenarioFromDesign(design, row.overrides),
			{
				debug: true,
				yieldMs: 1e9,
			},
		);
		const series = replay.debug!.series;
		for (const [key, expected] of [
			["theta_rad", row.theta_rad],
			["psi", row.psi_rad],
			["t", row.t_s],
		] as const) {
			const actual = series[key] as number[];
			expect(actual.length).toBe(expected.length);
			expect(
				Math.max(...actual.map((v, i) => Math.abs(v - expected[i]!))),
			).toBeLessThan(1e-10);
		}
		expect(replay.stalled).toBe(row.stalled);
		// The zero of progress follows settling; absolute phase retains that offset.
		const phase = series.theta_rad as number[];
		const progress = series.psi as number[];
		expect(Math.abs(phase[0]!)).toBeGreaterThan(1e-8);
		for (let i = 0; i < phase.length; i++)
			expect(
				Math.abs(phase[i]! - phase[0]! - row.direction * progress[i]!),
			).toBeLessThan(1e-12);
	},
);
