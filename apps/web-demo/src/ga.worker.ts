import { evolve, fitnessFlatStroke, fitnessHighStep } from "strandbeest-core";

export interface WorkerRequest {
	start: number[];
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
	const { start, objective, seed, generations, population } = e.data;
	const fitness =
		objective === "highstep" ? fitnessHighStep() : fitnessFlatStroke;
	const it = evolve(start, fitness, { seed, generations, population });
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
