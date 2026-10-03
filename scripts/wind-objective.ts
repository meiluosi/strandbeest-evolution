// Evolve legs for wind speed under the quasi-static model.  Usage: pnpm wind-objective [wind] [slopeDeg] [seeds]
import { writeFileSync } from "node:fs";
import {
	cycleSummary,
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	fitnessWindSpeed,
	gaitMetrics,
	genomeToParams,
	JANSEN_LENGTHS,
	JANSEN_PARAM_NAMES,
	type JansenParams,
	jansenSpec,
	paramsToGenome,
	runGA,
	trace,
	windWalk,
} from "../packages/core/src";

const wind = Number(process.argv[2] ?? 6);
const slopeDeg = Number(process.argv[3] ?? 0);
const seeds = Number(process.argv[4] ?? 5);
// Assumed resistance: 5% of weight, as in docs/EXPERIMENTS.md section 3.
const terrain = {
	slope: (slopeDeg * Math.PI) / 180,
	drag: 0.05 * DEFAULT_WALKER.mass * 9.81,
};
const fitness = fitnessWindSpeed({ wind, terrain });

const describe = (g: number[]) => {
	const spec = jansenSpec(genomeToParams(g));
	const s = cycleSummary(spec, DEFAULT_WALKER, terrain);
	const r = s ? windWalk(DEFAULT_SAIL, s, wind) : null;
	const m = gaitMetrics(trace(spec, 180).foot);
	return {
		speed: r?.speed ?? 0,
		startWind: r?.minStartWind ?? null,
		stride: s?.stride ?? 0,
		peakTorque: s?.peakTorque ?? 0,
		meanTorque: s?.meanTorque ?? 0,
		...m,
	};
};

/** Mean hip-to-foot distance: the leg's size. Lets us separate "bigger" from "better shaped". */
const reach = (p: JansenParams) => {
	const t = trace(jansenSpec(p), 90);
	return t.foot.reduce((s, q) => s + Math.hypot(q.x, q.y), 0) / t.foot.length;
};
const speedOf = (p: JansenParams) => {
	const s = cycleSummary(jansenSpec(p), DEFAULT_WALKER, terrain);
	return s ? windWalk(DEFAULT_SAIL, s, wind).speed : 0;
};
const atJansenSize = (p: JansenParams) => {
	const k = reach(JANSEN_LENGTHS) / reach(p);
	const scaled = Object.fromEntries(
		JANSEN_PARAM_NAMES.map((n) => [n, p[n] * k]),
	) as JansenParams;
	return { sizeRatio: 1 / k, speedAtJansenSize: speedOf(scaled) };
};

const start = paramsToGenome(JANSEN_LENGTHS);
const jansen = describe(start);
const runs = [];
for (let seed = 1; seed <= seeds; seed++) {
	const r = runGA(start, fitness, { seed, population: 60, generations: 60 });
	runs.push({
		seed,
		fitness: r.bestFitness,
		params: genomeToParams(r.best),
		...atJansenSize(genomeToParams(r.best)),
		...describe(r.best),
	});
	console.log(
		`seed ${seed}: speed ${runs.at(-1)?.speed.toFixed(3)} m/s (Jansen ${jansen.speed.toFixed(3)})  size ${runs.at(-1)?.sizeRatio.toFixed(2)}x, speed at Jansen's size ${runs.at(-1)?.speedAtJansenSize.toFixed(3)}  stride ${runs.at(-1)?.stride.toFixed(2)} m  peak ${runs.at(-1)?.peakTorque.toFixed(1)} N·m`,
	);
}
const file = `experiments/wind-objective-w${wind}-s${slopeDeg}.json`;
writeFileSync(
	file,
	`${JSON.stringify({ wind, slopeDeg, jansen, runs }, null, 2)}\n`,
);
console.log(file);
