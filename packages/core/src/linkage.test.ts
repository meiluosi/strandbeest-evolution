import { describe, expect, it } from "vitest";
import { JANSEN_LENGTHS, jansenSpec } from "./jansen";
import { solvePose, trace } from "./linkage";
import { gaitMetrics } from "./metrics";

const dist = (p: { x: number; y: number }, q: { x: number; y: number }) =>
	Math.hypot(p.x - q.x, p.y - q.y);

describe("Jansen linkage", () => {
	const spec = jansenSpec();

	it("preserves every link length at arbitrary crank angles", () => {
		const L = JANSEN_LENGTHS;
		for (const th of [0, 0.7, 2.1, 4.0, 5.5]) {
			const P = solvePose(spec, th);
			expect(P).not.toBeNull();
			const p = P as NonNullable<typeof P>;
			const g = p.G as { x: number; y: number };
			const at = (id: string) => p[id] as { x: number; y: number };
			expect(dist(at("C"), { x: L.a, y: L.l })).toBeCloseTo(L.m);
			expect(dist(at("K"), at("C"))).toBeCloseTo(L.j);
			expect(dist(at("K"), g)).toBeCloseTo(L.b);
			expect(dist(at("L"), at("K"))).toBeCloseTo(L.e);
			expect(dist(at("L"), g)).toBeCloseTo(L.d);
			expect(dist(at("M"), at("C"))).toBeCloseTo(L.k);
			expect(dist(at("M"), g)).toBeCloseTo(L.c);
			expect(dist(at("N"), at("L"))).toBeCloseTo(L.f);
			expect(dist(at("N"), at("M"))).toBeCloseTo(L.g);
			expect(dist(at("F"), at("M"))).toBeCloseTo(L.i);
			expect(dist(at("F"), at("N"))).toBeCloseTo(L.h);
		}
	});

	it("assembles over a full revolution with a continuous foot path", () => {
		const t = trace(spec, 180);
		expect(t.assembled).toBe(true);
		const m = gaitMetrics(t.foot);
		expect(t.maxStep).toBeLessThan(0.2 * m.width);
	});

	it("has a D-shaped foot path: a flat ground stroke and a raised return", () => {
		const m = gaitMetrics(trace(spec, 180).foot);
		expect(m.duty).toBeGreaterThan(0.3);
		expect(m.lift / m.width).toBeGreaterThan(0.2);
		expect(m.strokeLength / m.width).toBeGreaterThan(0.6);
	});

	it("returns null when the crank cannot close the linkage", () => {
		const broken = jansenSpec({ ...JANSEN_LENGTHS, j: 5 });
		expect(trace(broken, 60).assembled).toBe(false);
	});
});
