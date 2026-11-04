/** Reproducible boundary-inclusive timing; run after build-kernel-wasm.sh with pnpm exec tsx. */
import { readdirSync, readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import * as bindings from "../crates/beest-kernel/generated/beest_kernel.js";
import { fitnessFlatStroke } from "../packages/core/src/fitness";
import { runGA } from "../packages/core/src/ga";
import { genomeSpace } from "../packages/core/src/genome";
import {
	createWasmKinematicsKernel,
	installKinematicsKernel,
	referenceKinematicsKernel,
} from "../packages/core/src/kernel";
import type { LinkageSpec } from "../packages/core/src/linkage";

const binary = readFileSync(
	new URL(
		"../crates/beest-kernel/generated/beest_kernel_bg.wasm",
		import.meta.url,
	),
);
const started = performance.now();
bindings.initSync({ module: binary });
const initMs = performance.now() - started;
const wasm = createWasmKinematicsKernel(bindings);
const folder = new URL("../contracts/kinematics/", import.meta.url);
const specs = readdirSync(folder)
	.filter((f) => f.endsWith(".json"))
	.map((file) => ({
		file,
		spec: JSON.parse(readFileSync(new URL(file, folder), "utf8"))
			.spec as LinkageSpec,
	}));
function timing(operation: () => unknown, count: number): number {
	for (let i = 0; i < 20; i++) operation();
	const start = performance.now();
	for (let i = 0; i < count; i++) operation();
	return (performance.now() - start) / count;
}
const results = specs.map(({ file, spec }) => ({
	file,
	...Object.fromEntries(
		[referenceKinematicsKernel, wasm].map((kernel) => [
			kernel.name,
			{
				pose_ms: timing(() => kernel.solvePose(spec, 1.234), 2000),
				trace180_ms: timing(() => kernel.trace(spec, 180), 200),
				trace_and_gait_ms: timing(
					() => kernel.gaitMetrics(kernel.trace(spec, 180).foot, 0.015),
					200,
				),
			},
		]),
	),
}));
const gaSpec = specs.find((s) => s.file === "jansen.json")!.spec;
const ga = [referenceKinematicsKernel, wasm].map((kernel) => {
	installKinematicsKernel(kernel);
	const space = genomeSpace(gaSpec);
	const fitness = fitnessFlatStroke(space);
	let evaluations = 0;
	const start = performance.now();
	const result = runGA(
		space.toGenome(),
		(genome) => {
			evaluations++;
			return fitness(genome);
		},
		{ seed: 42, population: 50, generations: 19 },
	);
	return {
		kernel: kernel.name,
		elapsed_ms: performance.now() - start,
		evaluations,
		best: result.best,
		best_fitness: result.bestFitness,
	};
});
installKinematicsKernel(referenceKinematicsKernel);
const sameGenome = JSON.stringify(ga[0]!.best) === JSON.stringify(ga[1]!.best);
const fitnessDifference = Math.abs(ga[0]!.best_fitness - ga[1]!.best_fitness);
if (!sameGenome || fitnessDifference > 1e-9)
	throw new Error("fixed-seed GA parity failed");
console.log(
	JSON.stringify(
		{
			node: process.version,
			platform: process.platform,
			arch: process.arch,
			wasm_bytes: binary.length,
			wasm_gzip_bytes: gzipSync(binary).length,
			init_ms: initMs,
			units:
				"milliseconds per operation, host+binding conversion included; local warm run",
			results,
			ga: {
				seed: 42,
				population: 50,
				generations: 19,
				objective: "flat",
				same_genome: sameGenome,
				fitness_absolute_difference: fitnessDifference,
				results: ga,
			},
		},
		null,
		2,
	),
);
