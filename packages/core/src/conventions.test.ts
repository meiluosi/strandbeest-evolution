import { describe, expect, it } from "vitest";
import {
	hipToWorld,
	psiToTheta,
	thetaToMujocoQ,
	threeToWorld,
	worldToThree,
} from "./frames";
import { JANSEN_LENGTHS, jansenSpec } from "./jansen";
import { solvePose } from "./linkage";

const spec = jansenSpec();
const L = JANSEN_LENGTHS;

describe("conventions (docs/CONVENTIONS.md section 4)", () => {
	it("1. the crank tip follows theta counter-clockwise", () => {
		for (const th of [0, 0.7, 2.0, 4.1]) {
			const c = solvePose(spec, th)?.C as { x: number; y: number };
			expect(c.x).toBeCloseTo(L.a + L.m * Math.cos(th), 9);
			expect(c.y).toBeCloseTo(L.l + L.m * Math.sin(th), 9);
		}
	});

	it("2. with direction -1 the stance foot moves backward (x decreases) as psi increases", () => {
		const dir = -1 as const;
		const n = 720;
		const xs: number[] = [];
		const ys: number[] = [];
		for (let i = 0; i < n; i++) {
			const f = solvePose(spec, psiToTheta((2 * Math.PI * i) / n, dir))?.F as {
				x: number;
				y: number;
			};
			xs.push(f.x);
			ys.push(f.y);
		}
		const lo = Math.min(...ys);
		const width = Math.max(...xs) - Math.min(...xs);
		let sum = 0;
		let count = 0;
		for (let i = 0; i < n - 1; i++) {
			if (
				(ys[i] as number) < lo + 0.01 * width &&
				(ys[i + 1] as number) < lo + 0.01 * width
			) {
				sum += (xs[i + 1] as number) - (xs[i] as number);
				count++;
			}
		}
		expect(count).toBeGreaterThan(20);
		expect(sum / count).toBeLessThan(0);
	});

	it("2b. flipping the direction flips the stance motion (the test is sensitive to the sign)", () => {
		const n = 720;
		const stanceDx = (dir: -1 | 1) => {
			const xs: number[] = [];
			const ys: number[] = [];
			for (let i = 0; i < n; i++) {
				const f = solvePose(spec, psiToTheta((2 * Math.PI * i) / n, dir))
					?.F as { x: number; y: number };
				xs.push(f.x);
				ys.push(f.y);
			}
			const lo = Math.min(...ys);
			let s = 0;
			for (let i = 0; i < n - 1; i++)
				if ((ys[i] as number) < lo + 0.5 && (ys[i + 1] as number) < lo + 0.5)
					s += (xs[i + 1] as number) - (xs[i] as number);
			return s;
		};
		expect(stanceDx(-1)).toBeLessThan(0);
		expect(stanceDx(1)).toBeGreaterThan(0);
	});

	it("3. MuJoCo crank hinge angle is minus theta", () => {
		expect(thetaToMujocoQ(0.9)).toBe(-0.9);
		expect(psiToTheta(0.5, -1)).toBe(-0.5);
		expect(psiToTheta(0.5, 1)).toBe(0.5);
	});

	it("5. world -> three.js keeps forward as +x and turns up (+z) into +y; it is a rotation, not a mirror", () => {
		expect(worldToThree([1, 0, 0])).toEqual([1, 0, -0]);
		expect(worldToThree([0, 0, 1])).toEqual([0, 1, -0]);
		const [x, y, z] = worldToThree([0, 1, 0]);
		expect([x, y, z]).toEqual([0, 0, -1]);
		// determinant of the linear map is +1: x cross y = z must hold after mapping
		const ex = worldToThree([1, 0, 0]);
		const ey = worldToThree([0, 1, 0]);
		const cross = [
			ex[1] * ey[2] - ex[2] * ey[1],
			ex[2] * ey[0] - ex[0] * ey[2],
			ex[0] * ey[1] - ex[1] * ey[0],
		];
		const ez = worldToThree([0, 0, 1]);
		expect(cross.map((v) => v + 0)).toEqual([ez[0] + 0, ez[1] + 0, ez[2] + 0]);
		expect(threeToWorld(worldToThree([0.3, -0.2, 0.9]))).toEqual([
			0.3, -0.2, 0.9,
		]);
	});

	it("hip frame to world: y up becomes z up above the hip height", () => {
		expect(hipToWorld({ x: 10, y: -5 }, 0.002, 0.17, 0.01)).toEqual([
			0.02,
			0.01,
			0.17 - 0.01,
		]);
	});
});
