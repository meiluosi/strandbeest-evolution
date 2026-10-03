import { describe, expect, it } from "vitest";
import {
	cycleSummary,
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	FLAT,
	minStartWind,
	sailTorque,
	steadyOmega,
} from "./dynamics";
import { jansenSpec } from "./jansen";
import { simulateWalk } from "./timedomain";

const spec = jansenSpec();
const terrain = { slope: 0, drag: 0.05 * DEFAULT_WALKER.mass * 9.81 };
const summary = cycleSummary(spec, DEFAULT_WALKER, terrain) as NonNullable<
	ReturnType<typeof cycleSummary>
>;

describe("time-domain walk", () => {
	it("settles to a periodic motion whose mean speed is close to the quasi-static estimate", () => {
		const wind = 6;
		const r = simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, wind, {
			cycles: 30,
		});
		expect(r?.stalled).toBe(false);
		const omegaQs = steadyOmega(DEFAULT_SAIL, wind, summary.meanTorque);
		const vQs = omegaQs * (summary.stride / (2 * Math.PI));
		expect(Math.abs((r?.meanSpeed ?? 0) - vQs) / vQs).toBeLessThan(0.15);
	});

	it("is periodic after settling: crank speed repeats from one revolution to the next", () => {
		const r = simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, 6, {
			cycles: 40,
		});
		const n = 720;
		const a = r?.series[r.series.length - n + 100]?.omega ?? 0;
		const b = r?.series[r.series.length - 2 * n + 100]?.omega ?? 0;
		expect(Math.abs(a - b) / a).toBeLessThan(0.01);
	});

	it("stalls in a wind too weak to turn the crank", () => {
		const r = simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, 0.1, {
			cycles: 5,
		});
		expect(r?.stalled).toBe(true);
	});

	it("more rotor inertia smooths the speed ripple within a revolution", () => {
		const light = simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, 6, {
			inertia: 0.05,
			cycles: 30,
		});
		const heavy = simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, 6, {
			inertia: 60,
			cycles: 30,
		});
		const spread = (r: typeof light) =>
			((r?.speedRange[1] ?? 0) - (r?.speedRange[0] ?? 0)) / (r?.meanSpeed ?? 1);
		expect(spread(heavy)).toBeLessThan(spread(light));
	});

	it("a heavy rotor coasts further through a calm spell than a light one", () => {
		const lull = (t: number) => (t < 40 ? 6 : 0);
		const run = (inertia: number) =>
			simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, lull, {
				inertia,
				cycles: 12,
				omega0: 0.5,
			});
		const revsAfter = (r: ReturnType<typeof run>) => {
			const stalledRev = r?.stalled
				? r.revolutions
				: (r?.series.at(-1)?.psi ?? 0) / (2 * Math.PI);
			return (
				stalledRev -
				(r?.series.find((p) => p.t >= 40)?.psi ?? 0) / (2 * Math.PI)
			);
		};
		expect(revsAfter(run(300))).toBeGreaterThan(revsAfter(run(0.05)));
	});

	it("returns null when the leg cannot assemble", () => {
		const bad = jansenSpec({ ...spec.params, j: 5 } as never);
		expect(simulateWalk(bad, DEFAULT_WALKER, FLAT, DEFAULT_SAIL, 6)).toBeNull();
	});
});
