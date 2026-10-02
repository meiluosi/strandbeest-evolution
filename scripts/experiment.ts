// Usage: pnpm experiment [flat|highstep] [seed] [generations]
import { mkdirSync, writeFileSync } from "node:fs";
import {
	fitnessFlatStroke,
	fitnessHighStep,
	gaitMetrics,
	genomeToParams,
	JANSEN_LENGTHS,
	jansenSpec,
	paramsToGenome,
	runGA,
	trace,
} from "../packages/core/src";

const objective = process.argv[2] ?? "flat";
const seed = Number(process.argv[3] ?? 1);
const generations = Number(process.argv[4] ?? 80);
const fitness =
	objective === "highstep" ? fitnessHighStep() : fitnessFlatStroke;

const start = paramsToGenome(JANSEN_LENGTHS);
const result = runGA(start, fitness, { seed, population: 80, generations });
const describe = (g: number[]) =>
	gaitMetrics(trace(jansenSpec(genomeToParams(g)), 180).foot);

const out = {
	objective,
	seed,
	generations,
	original: { fitness: fitness(start), metrics: describe(start) },
	evolved: {
		fitness: result.bestFitness,
		params: genomeToParams(result.best),
		metrics: describe(result.best),
	},
	history: result.history.map((h) => ({
		g: h.generation,
		best: h.bestFitness,
		mean: h.meanFitness,
	})),
};
mkdirSync("experiments", { recursive: true });
const file = `experiments/${objective}-seed${seed}.json`;
writeFileSync(file, `${JSON.stringify(out, null, 2)}\n`);
console.log(file);
console.log("original", out.original.fitness.toFixed(3), out.original.metrics);
console.log("evolved ", out.evolved.fitness.toFixed(3), out.evolved.metrics);
