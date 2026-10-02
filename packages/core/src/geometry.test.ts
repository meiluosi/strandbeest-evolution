import { describe, expect, it } from "vitest";
import { circleIntersection } from "./geometry";

describe("circleIntersection", () => {
	it("finds both solutions of a 3-4-5 triangle", () => {
		const o = { x: 0, y: 0 };
		const p = { x: 5, y: 0 };
		const left = circleIntersection(o, 3, p, 4, 1);
		const right = circleIntersection(o, 3, p, 4, -1);
		expect(left?.x).toBeCloseTo(1.8);
		expect(left?.y).toBeCloseTo(2.4);
		expect(right?.y).toBeCloseTo(-2.4);
	});

	it("returns null when circles are too far apart", () => {
		expect(
			circleIntersection({ x: 0, y: 0 }, 1, { x: 10, y: 0 }, 1, 1),
		).toBeNull();
	});
});
