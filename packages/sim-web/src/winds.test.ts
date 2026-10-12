import { describe, expect, it } from "vitest";
import { simConfig } from "./config";
import { makeWind } from "./winds";

const wind = (w: Record<string, unknown>) =>
	makeWind(simConfig({ wind: w }).wind);

// the same three shapes as strandbeest_sim.winds; the run corpus (contracts/sim-run, sail-* cases) checks them inside a run
describe("winds", () => {
	it("constant: the speed at every time", () => {
		const f = wind({ kind: "constant", speed: 3.5 });
		expect([f(0), f(7.3), f(1e4)]).toEqual([3.5, 3.5, 3.5]);
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

	it("refuses an unknown wind", () => {
		expect(() => wind({ kind: "hurricane" })).toThrow(/unknown wind/);
	});
});
