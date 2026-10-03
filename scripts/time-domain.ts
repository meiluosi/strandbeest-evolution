// What does rotor inertia change?  Usage: pnpm time-domain
import { writeFileSync } from "node:fs";
import {
	cycleSummary,
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	jansenSpec,
	minStartWind,
	simulateWalk,
} from "../packages/core/src";

const spec = jansenSpec();
const terrain = { slope: 0, drag: 0.05 * DEFAULT_WALKER.mass * 9.81 }; // 5 % of weight, assumed
const summary = cycleSummary(spec, DEFAULT_WALKER, terrain);
if (!summary) throw new Error("Jansen leg failed to assemble");

const out: Record<string, unknown> = {
	assumptions: { walker: DEFAULT_WALKER, sail: DEFAULT_SAIL, terrain },
};

// (a) lowest wind that starts the walker from rest, by bisection, for several rotor inertias
const startsFromRest = (wind: number, inertia: number) =>
	simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, wind, {
		inertia,
		cycles: 3,
	})?.stalled === false;
const qs = minStartWind(DEFAULT_SAIL, summary.peakTorque);
const starts = [0.05, 2, 60, 300].map((inertia) => {
	let lo = 0.1;
	let hi = 3;
	for (let i = 0; i < 30; i++) {
		const mid = (lo + hi) / 2;
		if (startsFromRest(mid, inertia)) hi = mid;
		else lo = mid;
	}
	return { inertia, minStartWind: hi };
});
console.log("quasi-static start wind", qs.toFixed(3));
for (const s of starts)
	console.log(
		`J ${String(s.inertia).padStart(5)} kg·m²: start wind ${s.minStartWind.toFixed(3)} m/s`,
	);
out.quasiStaticStartWind = qs;
out.startWind = starts;

// (b) speed ripple at 6 m/s
const ripple = [0.05, 2, 60, 300].map((inertia) => {
	const r = simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, 6, {
		inertia,
		cycles: 30,
	});
	return {
		inertia,
		meanSpeed: r?.meanSpeed,
		min: r?.speedRange[0],
		max: r?.speedRange[1],
	};
});
for (const r of ripple)
	console.log(
		`J ${String(r.inertia).padStart(5)}: mean ${r.meanSpeed?.toFixed(3)} m/s, range ${r.min?.toFixed(3)}–${r.max?.toFixed(3)}`,
	);
out.ripple = ripple;

// (c) revolutions coasted after the wind drops to zero at t = 40 s
const lull = (t: number) => (t < 40 ? 6 : 0);
const coast = [0.05, 2, 60, 300].map((inertia) => {
	const r = simulateWalk(spec, DEFAULT_WALKER, terrain, DEFAULT_SAIL, lull, {
		inertia,
		cycles: 12,
		omega0: 0.5,
	});
	const at = (r?.series.find((p) => p.t >= 40)?.psi ?? 0) / (2 * Math.PI);
	const end = r?.stalled
		? (r.revolutions ?? 0)
		: (r?.series.at(-1)?.psi ?? 0) / (2 * Math.PI);
	return { inertia, revolutionsAfterLull: end - at, stalled: r?.stalled };
});
for (const c of coast)
	console.log(
		`J ${String(c.inertia).padStart(5)}: coasts ${c.revolutionsAfterLull.toFixed(2)} rev after the wind drops`,
	);
out.coast = coast;

writeFileSync(
	"experiments/time-domain.json",
	`${JSON.stringify(out, null, 2)}\n`,
);
