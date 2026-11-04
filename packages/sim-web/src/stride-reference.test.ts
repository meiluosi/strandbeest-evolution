import { readFileSync } from "node:fs";
import { type LinkageSpec, solvePose } from "strandbeest-core";
import { expect, it } from "vitest";
import { fitSupportVelocity, lowestFootStride } from "./stride-reference";

const corpus = JSON.parse(
	readFileSync(
		new URL(
			"../../../experiments/hardening-g1-signed-stride-events-2026-11-03.json",
			import.meta.url,
		),
		"utf8",
	),
) as {
	analytic_checks: {
		legs: number;
		direction: number;
		amplitude: number;
		expected_stride: number;
	}[];
	rows: {
		case: number;
		spec: LinkageSpec;
		walker: { legs: number; direction: number; unit: number };
		endpoint_references: { brackets: number; stride: number }[];
	}[];
};

it("distinguishes compatible, conflicting and missing supports", () => {
	expect(fitSupportVelocity([-2])).toEqual({
		velocity: 2,
		rmsSlip: 0,
		spread: 0,
	});
	expect(fitSupportVelocity([2, 2])).toEqual({
		velocity: -2,
		rmsSlip: 0,
		spread: 0,
	});
	expect(fitSupportVelocity([-2, 2])).toEqual({
		velocity: 0,
		rmsSlip: 2,
		spread: 4,
	});
	expect(fitSupportVelocity([]).velocity).toBeNull();
	expect(
		lowestFootStride(() => ({ x: 0, y: 0 }), [], 1, 1, 72).stride,
	).toBeNull();
});

it.each(corpus.analytic_checks)(
	"matches the analytic signed ellipse integral ($legs, $direction, $amplitude)",
	(row) => {
		const expected =
			-row.direction *
			2 *
			row.legs *
			row.amplitude *
			Math.sin(Math.PI / row.legs);
		expect(expected).toBe(row.expected_stride);
		const result = lowestFootStride(
			(a) => ({ x: row.amplitude * Math.cos(a), y: Math.sin(a) }),
			Array.from({ length: row.legs }, (_, j) => (2 * Math.PI * j) / row.legs),
			row.direction,
			1,
			72,
		);
		expect(Math.abs(result.stride! - expected)).toBeLessThanOrEqual(
			Math.abs(expected) * 1e-12 + 1e-24,
		);
	},
);

it.each(corpus.rows)(
	"matches native Python/Rust endpoint reference for case $case",
	(row) => {
		for (const expected of row.endpoint_references) {
			const result = lowestFootStride(
				(angle) => solvePose(row.spec, angle)![row.spec.foot]!,
				Array.from(
					{ length: row.walker.legs },
					(_, j) => (2 * Math.PI * j) / row.walker.legs,
				),
				row.walker.direction,
				row.walker.unit,
				expected.brackets,
			);
			expect(Math.abs(result.stride! - expected.stride)).toBeLessThan(1e-12);
		}
	},
);
