import { describe, expect, it } from "vitest";
import { circleIntersection } from "./geometry";
import { jansenSpec } from "./jansen";
import { solvePose, trace } from "./linkage";
import { gaitMetrics } from "./metrics";
import { groundContactCounts } from "./multileg";
import { referenceGaitMetrics } from "./reference-kinematics";

describe("Kinematics Invariants and Numerical Robustness", () => {
	it("preserves exact link lengths across the entire 360-degree crank cycle", () => {
		const spec = jansenSpec();
		const samples = 72;
		for (let i = 0; i < samples; i++) {
			const theta = (2 * Math.PI * i) / samples;
			const pose = solvePose(spec, theta);
			expect(pose).not.toBeNull();
			if (!pose) continue;

			// Verify each joint's distance to its center definitions
			for (const joint of spec.joints) {
				const pt = pose[joint.id];
				expect(pt).toBeDefined();
				if (!pt) continue;

				for (let k = 0; k < 2; k++) {
					const centerId = joint.centers[k] as string;
					const radiusParam = joint.radii[k] as string;
					const expectedR =
						typeof radiusParam === "number"
							? radiusParam
							: (spec.params[radiusParam] as number);
					const centerPt = pose[centerId];
					expect(centerPt).toBeDefined();
					if (!centerPt) continue;

					const actualR = Math.hypot(pt.x - centerPt.x, pt.y - centerPt.y);
					expect(actualR).toBeCloseTo(expectedR, 6);
				}
			}
		}
	});

	it("preserves kinematic scaling invariants and duty cycle under uniform geometric scaling", () => {
		const specBase = jansenSpec();
		const tBase = trace(specBase, 60);
		expect(tBase.assembled).toBe(true);

		// Uniformly scale all geometric parameters by 1.85
		const scaleFactor = 1.85;
		const scaledParams = Object.fromEntries(
			Object.entries(specBase.params).map(([k, v]) => [k, v * scaleFactor]),
		);
		const specScaled = jansenSpec(scaledParams as never);

		const tScaled = trace(specScaled, 60);
		expect(tScaled.assembled).toBe(true);
		expect(tScaled.foot.length).toBe(tBase.foot.length);

		for (let i = 0; i < tBase.foot.length; i++) {
			const p0 = tBase.foot[i]!;
			const p1 = tScaled.foot[i]!;
			expect(p1.x).toBeCloseTo(p0.x * scaleFactor, 5);
			expect(p1.y).toBeCloseTo(p0.y * scaleFactor, 5);
		}

		// Gait metrics scaling laws: dimensions scale proportionally, duty cycle is invariant
		const m0 = gaitMetrics(tBase.foot);
		const m1 = gaitMetrics(tScaled.foot);
		expect(m1.width).toBeCloseTo(m0.width * scaleFactor, 5);
		expect(m1.lift).toBeCloseTo(m0.lift * scaleFactor, 5);
		expect(m1.strokeLength).toBeCloseTo(m0.strokeLength * scaleFactor, 5);
		expect(m1.duty).toBeCloseTo(m0.duty, 5);
	});

	it("prevents float overflow from returning NaN coordinates in circleIntersection", () => {
		// Large numbers exceeding sqrt(Number.MAX_VALUE) ~ 1.34e154
		const p0 = { x: 0, y: 0 };
		const p1 = { x: 1e160, y: 0 };
		const r0 = 1e160;
		const r1 = 1e160;

		const result = circleIntersection(p0, r0, p1, r1, 1);
		// Must safely return null rather than { x: NaN, y: NaN }
		expect(result).toBeNull();
	});

	it("handles non-finite inputs safely in circleIntersection", () => {
		expect(
			circleIntersection({ x: 0, y: 0 }, Number.NaN, { x: 1, y: 0 }, 1, 1),
		).toBeNull();
		expect(
			circleIntersection(
				{ x: 0, y: 0 },
				1,
				{ x: Number.POSITIVE_INFINITY, y: 0 },
				1,
				1,
			),
		).toBeNull();
	});

	it("evaluates large sample sizes (N = 100,000) without call stack overflow", () => {
		const n = 100_000;
		const largeFoot = Array.from({ length: n }, (_, i) => {
			const angle = (2 * Math.PI * i) / n;
			return {
				x: Math.cos(angle) * 10,
				y: Math.sin(angle) * 5 - 20,
			};
		});

		// Ensure referenceGaitMetrics does not throw "Maximum call stack size exceeded"
		const m = referenceGaitMetrics(largeFoot);
		expect(m.width).toBeCloseTo(20, 1);
		expect(m.lift).toBeCloseTo(10, 1);
		expect(m.duty).toBeGreaterThan(0);

		// Ensure groundContactCounts also handles large arrays without stack overflow
		const counts = groundContactCounts([largeFoot]);
		expect(counts.length).toBe(n);
	});

	it("gracefully handles empty feet arrays in groundContactCounts", () => {
		expect(groundContactCounts([])).toEqual([]);
		expect(groundContactCounts([[]])).toEqual([]);
	});
});
