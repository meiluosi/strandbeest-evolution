import { describe, expect, it } from "vitest";
import {
	frameAt,
	hull,
	insidePolygon,
	largestDifference,
	type Replay,
} from "./replay-types";

const replay = (t: number[], x: (i: number) => number): Replay =>
	({ t, pos: t.map((_, i) => [[x(i), 0, 0]]) }) as unknown as Replay;

describe("replay helpers", () => {
	it("hull of a square with an interior point is the square", () => {
		const h = hull([
			[0, 0],
			[1, 0],
			[1, 1],
			[0, 1],
			[0.5, 0.5],
		]);
		expect(h).toHaveLength(4);
		expect(new Set(h.map((p) => p.join(",")))).toEqual(
			new Set(["0,0", "1,0", "1,1", "0,1"]),
		);
	});
	it("hull of fewer than three points is those points", () => {
		expect(
			hull([
				[0, 0],
				[1, 1],
			]),
		).toHaveLength(2);
	});
	it("point in polygon", () => {
		const sq = hull([
			[0, 0],
			[2, 0],
			[2, 2],
			[0, 2],
		]);
		expect(insidePolygon([1, 1], sq)).toBe(true);
		expect(insidePolygon([3, 1], sq)).toBe(false);
		expect(insidePolygon([-0.1, 1], sq)).toBe(false);
	});
	it("frameAt rounds to the nearest recorded frame and clamps", () => {
		const r = replay([0, 0.1, 0.2, 0.3], () => 0);
		expect(frameAt(r, 0.14)).toBe(1);
		expect(frameAt(r, 0.16)).toBe(2);
		expect(frameAt(r, -1)).toBe(0);
		expect(frameAt(r, 9)).toBe(3);
	});
	it("largestDifference finds the instant where two runs part ways", () => {
		const t = Array.from({ length: 101 }, (_, i) => i / 10);
		const a = replay(t, () => 0);
		const b = replay(t, (i) => (i < 60 ? 0 : (i - 60) * 0.01)); // identical until t = 6 s, then B drifts away
		const d = largestDifference(a, b);
		expect(d?.t).toBeCloseTo(10, 1);
		expect(d?.distance).toBeCloseTo(0.4, 2);
	});
});
