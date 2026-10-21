import { describe, expect, it } from "vitest";
import { simConfig } from "./config";
import { makeWind } from "./winds";

const wind = (w: Record<string, unknown>) =>
	makeWind(simConfig({ wind: w }).wind);

describe("winds", () => {
	it("constant: the speed at every time", () => {
		const f = wind({ kind: "constant", speed: 3.5 });
		expect([f(0), f(7.3), f(1e4)]).toEqual([3.5, 3.5, 3.5]);
	});

	it("constant with yaw angle", () => {
		const f = wind({
			kind: "constant",
			speed: 6.0,
			params: { yaw_deg: 60 },
		});
		expect(f(0)).toBeCloseTo(3.0, 10); // cos(60°) = 0.5
	});

	it("gusts: mean plus a sine of the given amplitude and period, never negative", () => {
		const f = wind({
			kind: "gusts",
			speed: 3,
			params: { amplitude: 2, period: 4 },
		});
		expect(f(0)).toBeCloseTo(3, 12);
		expect(f(1)).toBeCloseTo(5, 12); // a quarter period: the crest
		expect(f(3)).toBeCloseTo(1, 12); // three quarters: the trough
		const strong = wind({
			kind: "gusts",
			speed: 1,
			params: { amplitude: 5, period: 4 },
		});
		expect(strong(3)).toBe(0);
	});

	it("gusts use amplitude 1 and period 6 by default", () => {
		const f = wind({ kind: "gusts", speed: 2 });
		expect(f(1.5)).toBeCloseTo(3, 12);
	});

	it("lull: steady, then zero from `at` on", () => {
		const f = wind({ kind: "lull", speed: 4, params: { at: 2 } });
		expect([f(0), f(1.999), f(2), f(9)]).toEqual([4, 4, 0, 0]);
		expect(wind({ kind: "lull", speed: 4 })(9.9)).toBe(4); // default `at` is 10 s
	});

	it("shear: power-law vertical boundary layer profile", () => {
		const f = wind({
			kind: "shear",
			speed: 10,
			params: { z_ref: 1.0, alpha: 0.14, profile: "power" },
		});
		expect(f(0, 1.0)).toBeCloseTo(10.0, 6);
		expect(f(0, 0.2)).toBeCloseTo(10.0 * 0.2 ** 0.14, 6);
		expect(f(0, 2.0)).toBeCloseTo(10.0 * 2.0 ** 0.14, 6);
	});

	it("turbulent: exact match with Python strandbeest_sim.winds", () => {
		const f = wind({
			kind: "turbulent",
			speed: 5.0,
			params: {
				seed: 42,
				intensity: 0.15,
				integral_length: 25.0,
				dt: 0.05,
			},
		});
		// Exactly matches Python reference: [4.891932, 4.801267, 5.04059, 5.730477]
		expect(f(0.0)).toBeCloseTo(4.891932, 5);
		expect(f(0.5)).toBeCloseTo(4.801267, 5);
		expect(f(1.0)).toBeCloseTo(5.04059, 5);
		expect(f(5.0)).toBeCloseTo(5.730477, 5);
	});

	it("profile_turbulent: combines vertical shear and turbulence", () => {
		const f = wind({
			kind: "profile_turbulent",
			speed: 6.0,
			params: {
				z_ref: 1.0,
				alpha: 0.14,
				intensity: 0.1,
				seed: 99,
				yaw_deg: 30,
			},
		});
		const vGround = f(1.0, 0.1);
		const vHigh = f(1.0, 2.0);
		expect(vHigh).toBeGreaterThan(vGround);
	});

	it("refuses an unknown wind", () => {
		expect(() => wind({ kind: "hurricane" })).toThrow(/unknown wind/);
	});
});
