// How much wind does a leg design need?  Usage: pnpm dynamics

import { existsSync, readFileSync } from "node:fs";
import {
	cycleSummary,
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	FLAT,
	genomeToParams,
	JANSEN_LENGTHS,
	jansenSpec,
	windWalk,
} from "../packages/core/src";

const designs: Record<string, ReturnType<typeof jansenSpec>> = {
	jansen: jansenSpec(),
};
for (const f of ["flat-seed1", "highstep-seed1"]) {
	const p = `experiments/${f}.json`;
	if (existsSync(p))
		designs[`evolved:${f}`] = jansenSpec(
			JSON.parse(readFileSync(p, "utf8")).evolved.params,
		);
}
void genomeToParams;
void JANSEN_LENGTHS;

// Assumed rolling/foot resistance: 5% of weight. Not measured.
const ROLL = 0.05;

for (const [name, spec] of Object.entries(designs)) {
	for (const slopeDeg of [0, 10]) {
		const s = cycleSummary(spec, DEFAULT_WALKER, {
			slope: (slopeDeg * Math.PI) / 180,
			drag: ROLL * DEFAULT_WALKER.mass * 9.81,
		});
		if (!s) {
			console.log(name, "cannot assemble");
			continue;
		}
		const w = [4, 8, 12]
			.map((v) => windWalk(DEFAULT_SAIL, s, v).speed.toFixed(2))
			.join(" / ");
		console.log(
			`${name.padEnd(22)} slope ${String(slopeDeg).padStart(2)}°  stride ${s.stride.toFixed(2)} m  peak ${s.peakTorque.toFixed(1)} N·m` +
				`  mean ${s.meanTorque.toFixed(1)}  stable ${(s.stableFraction * 100).toFixed(0)}%  start wind ${windWalk(DEFAULT_SAIL, s, 0).minStartWind.toFixed(1)} m/s  speed@4/8/12 ${w} m/s`,
		);
	}
}
void FLAT;
