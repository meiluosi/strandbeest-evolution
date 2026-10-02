import { describe, expect, it } from "vitest";
import {
	cycleSummary,
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	FLAT,
	G,
	minStartWind,
	sailTorque,
	steadyOmega,
	windWalk,
} from "./dynamics";
import { jansenSpec } from "./jansen";

const spec = jansenSpec();

describe("quasi-static dynamics", () => {
	it("walks forward with a positive stride when the crank turns the Jansen direction", () => {
		const s = cycleSummary(spec, DEFAULT_WALKER, FLAT);
		expect(s).not.toBeNull();
		expect((s as NonNullable<typeof s>).stride).toBeGreaterThan(0);
	});

	it("net work per revolution is zero on flat ground without drag (energy conservation)", () => {
		const s = cycleSummary(spec, DEFAULT_WALKER, FLAT) as NonNullable<
			ReturnType<typeof cycleSummary>
		>;
		// the lowest-foot height has kinks, so the discrete sum is only accurate to ~1% of the peak torque
		expect(Math.abs(s.meanTorque)).toBeLessThan(1e-2 * s.peakTorque);
	});

	it("net work per revolution equals (m g sinα + drag) × stride", () => {
		const terrain = { slope: 0.2, drag: 15 };
		const s = cycleSummary(spec, DEFAULT_WALKER, terrain) as NonNullable<
			ReturnType<typeof cycleSummary>
		>;
		const expected =
			(DEFAULT_WALKER.mass * G * Math.sin(terrain.slope) + terrain.drag) *
			s.stride;
		expect(
			Math.abs(s.meanTorque * 2 * Math.PI - expected) / expected,
		).toBeLessThan(1e-3);
	});

	it("peak torque scales linearly with mass", () => {
		const a = cycleSummary(
			spec,
			{ ...DEFAULT_WALKER, mass: 50 },
			FLAT,
		) as NonNullable<ReturnType<typeof cycleSummary>>;
		const b = cycleSummary(
			spec,
			{ ...DEFAULT_WALKER, mass: 100 },
			FLAT,
		) as NonNullable<ReturnType<typeof cycleSummary>>;
		expect(b.peakTorque / a.peakTorque).toBeCloseTo(2, 5);
	});

	it("is stable with many legs and not with one", () => {
		const many = cycleSummary(
			spec,
			{ ...DEFAULT_WALKER, legs: 12 },
			FLAT,
		) as NonNullable<ReturnType<typeof cycleSummary>>;
		const one = cycleSummary(
			spec,
			{ ...DEFAULT_WALKER, legs: 1 },
			FLAT,
		) as NonNullable<ReturnType<typeof cycleSummary>>;
		expect(many.stableFraction).toBeGreaterThan(0.9);
		expect(one.stableFraction).toBeLessThan(0.5);
	});

	it("steeper slope needs more torque", () => {
		const flat = cycleSummary(spec, DEFAULT_WALKER, FLAT) as NonNullable<
			ReturnType<typeof cycleSummary>
		>;
		const hill = cycleSummary(spec, DEFAULT_WALKER, {
			slope: 0.15,
			drag: 0,
		}) as NonNullable<ReturnType<typeof cycleSummary>>;
		expect(hill.meanTorque).toBeGreaterThan(flat.meanTorque);
	});
});

describe("wind", () => {
	it("sail torque falls to zero when the sail moves as fast as the wind", () => {
		expect(
			sailTorque(
				DEFAULT_SAIL,
				5,
				5 / (DEFAULT_SAIL.radius * DEFAULT_SAIL.gear),
			),
		).toBe(0);
		expect(sailTorque(DEFAULT_SAIL, 5, 0)).toBeGreaterThan(0);
	});

	it("min start wind balances the standstill torque against the peak", () => {
		const w = minStartWind(DEFAULT_SAIL, 3);
		expect(sailTorque(DEFAULT_SAIL, w, 0)).toBeCloseTo(
			3 + DEFAULT_SAIL.friction,
			6,
		);
	});

	it("more wind gives a higher steady speed, and none gives none", () => {
		const s = cycleSummary(spec, DEFAULT_WALKER, FLAT) as NonNullable<
			ReturnType<typeof cycleSummary>
		>;
		const calm = windWalk(DEFAULT_SAIL, s, 0);
		const fresh = windWalk(DEFAULT_SAIL, s, 6);
		const gale = windWalk(DEFAULT_SAIL, s, 12);
		expect(calm.speed).toBe(0);
		expect(gale.speed).toBeGreaterThan(fresh.speed);
		expect(steadyOmega(DEFAULT_SAIL, 6, 0)).toBeGreaterThan(0);
	});
});
