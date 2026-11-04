import {
	evolve,
	fitnessFlatStroke,
	fitnessHighStep,
	genomeSpace,
	type LinkageSpec,
} from "strandbeest-core";

import { initializeKernel } from "./kernel-loader";

export interface WorkerRequest {
	/** the linkage to start from; the search varies its named lengths and keeps the topology */
	spec: LinkageSpec;
	objective: "flat" | "highstep";
	seed: number;
	generations: number;
	population: number;
}

let requestId = 0;

self.onmessage = async (e: MessageEvent<WorkerRequest | "stop">) => {
	const id = ++requestId;
	if (e.data === "stop") {
		self.postMessage({ type: "stopped" });
		return;
	}
	try {
		const kernel = await initializeKernel();
		if (id !== requestId) return;
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
		const step = () => {
			if (id !== requestId) return;
			try {
				const r = it.next();
				if (r.done) return self.postMessage({ type: "done", kernel });
				self.postMessage({ type: "state", state: r.value, kernel });
				setTimeout(step, 0);
			} catch (error) {
				self.postMessage({
					type: "error",
					message: error instanceof Error ? error.message : String(error),
				});
			}
		};
		step();
	} catch (error) {
		if (id === requestId)
			self.postMessage({
				type: "error",
				message: error instanceof Error ? error.message : String(error),
			});
	}
};
