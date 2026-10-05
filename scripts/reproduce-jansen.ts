// Can evolution find Jansen's leg from scratch?  Usage: pnpm reproduce [seeds] [generations] [population] [default|tuned]
//   A) match:  inverse problem — fit the foot-loop shape of Jansen's leg, starting from random lengths.
//   B) flat:   objective-driven — maximise our flat-stroke fitness from random lengths, then compare to Jansen.
// "blind" search box: every length uniform in [5, 80], no knowledge of Jansen's numbers except their order of magnitude.
import { mkdirSync, writeFileSync } from "node:fs";
import {
	fitnessFlatStroke,
	fitnessMatchPath,
	gaitMetrics,
	genomeToParams,
	JANSEN_LENGTHS,
	JANSEN_PARAM_NAMES,
	JANSEN_SPACE,
	jansenSpec,
	paramsToGenome,
	pathDistance,
	runGA,
	trace,
} from "../packages/core/src";

const seeds = Number(process.argv[2] ?? 20);
const generations = Number(process.argv[3] ?? 500);
const population = Number(process.argv[4] ?? 150);
// "tuned": high mutation rate/scale + more elites, chosen from a small sweep to avoid premature convergence.
const mode = process.argv[5] ?? "default";
const gaTuning =
	mode === "tuned" ? { mutationRate: 0.5, mutationScale: 0.15, elites: 3 } : {};

const jansen = paramsToGenome(JANSEN_LENGTHS);
const flatStroke = fitnessFlatStroke(JANSEN_SPACE);
const jansenFoot = trace(jansenSpec(), 180).foot;
const blindCentre = jansen.map(() => 40);
const blindBounds: [number, number] = [5 / 40, 80 / 40];

/** mean |log ratio| of lengths after the best uniform rescaling; 0 = identical lengths up to scale. */
function lengthError(g: number[]): number {
	const logs = g.map((v, i) => Math.log(v / (jansen[i] as number)));
	const mean = logs.reduce((s, v) => s + v, 0) / logs.length;
	return logs.reduce((s, v) => s + Math.abs(v - mean), 0) / logs.length;
}

const shape = (g: number[]) =>
	pathDistance(trace(jansenSpec(genomeToParams(g)), 180).foot, jansenFoot);
const matchFitness = fitnessMatchPath(JANSEN_SPACE, jansenFoot);

const rows = [];
for (let seed = 1; seed <= seeds; seed++) {
	const opts = {
		seed,
		generations,
		population,
		init: "uniform" as const,
		bounds: blindBounds,
		...gaTuning,
	};
	const a = runGA(blindCentre, matchFitness, opts);
	const b = runGA(blindCentre, flatStroke, opts);
	const row = {
		seed,
		match: {
			shapeDistance: shape(a.best),
			lengthError: lengthError(a.best),
			genome: a.best,
		},
		flat: {
			fitness: b.bestFitness,
			shapeDistance: shape(b.best),
			metrics: gaitMetrics(trace(jansenSpec(genomeToParams(b.best)), 180).foot),
			genome: b.best,
		},
	};
	rows.push(row);
	console.log(
		`seed ${String(seed).padStart(2)}  match: shape ${row.match.shapeDistance.toFixed(4)} lenErr ${row.match.lengthError.toFixed(3)}` +
			`   flat: fit ${row.flat.fitness.toFixed(3)} shape ${row.flat.shapeDistance.toFixed(3)}`,
	);
}

const med = (xs: number[]) =>
	[...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)] as number;
const jansenFit = flatStroke(jansen);
const summary = {
	params: {
		seeds,
		generations,
		population,
		mode,
		gaTuning,
		searchBox: "uniform [5,80] per length",
	},
	jansen: { flatFitness: jansenFit, metrics: gaitMetrics(jansenFoot) },
	match: {
		medianShapeDistance: med(rows.map((r) => r.match.shapeDistance)),
		recoveredShape: rows.filter((r) => r.match.shapeDistance < 0.02).length,
		recoveredLengths: rows.filter((r) => r.match.lengthError < 0.1).length,
	},
	flat: {
		medianFitness: med(rows.map((r) => r.flat.fitness)),
		beatJansenFitness: rows.filter((r) => r.flat.fitness > jansenFit).length,
		medianShapeDistance: med(rows.map((r) => r.flat.shapeDistance)),
		closeToJansenShape: rows.filter((r) => r.flat.shapeDistance < 0.05).length,
	},
};
console.log(JSON.stringify(summary, null, 2));
mkdirSync("experiments", { recursive: true });
writeFileSync(
	`experiments/reproduce-jansen-${mode}-ga.json`,
	`${JSON.stringify({ summary, rows, names: JANSEN_PARAM_NAMES }, null, 2)}\n`,
);
