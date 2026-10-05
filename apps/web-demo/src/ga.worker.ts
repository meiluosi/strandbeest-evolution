import {
	evolve,
	fitnessFlatStroke,
	fitnessHighStep,
	genomeSpace,
	type LinkageSpec,
} from "strandbeest-core";

export interface WorkerRequest {
	/** the linkage to start from; the search varies its named lengths and keeps the topology */
	spec: LinkageSpec;
	objective: "flat" | "highstep";
	seed: number;
	generations: number;
	population: number;
}

let stopped = false;

self.onmessage = (e: MessageEvent<WorkerRequest | "stop">) => {
	if (e.data === "stop") {
		stopped = true;
		return;
	}
	stopped = false;
	const { spec, objective, seed, generations, population } = e.data;
	const space = genomeSpace(spec);
	const fitness =
		objective === "highstep"
			? fitnessHighStep(space)
			: fitnessFlatStroke(space);
	const it = evolve(space.toGenome(), fitness, {
		seed,
		generations,
		population,
	});
	// Run synchronously in the worker; check the stop flag between generations via a macrotask hop.
	const step = () => {
		if (stopped) return self.postMessage({ type: "stopped" });
		const r = it.next();
		if (r.done) return self.postMessage({ type: "done" });
		self.postMessage({ type: "state", state: r.value });
		setTimeout(step, 0);
	};
	step();
};
