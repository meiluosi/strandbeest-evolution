/** The browser simulator: MuJoCo WebAssembly in a worker, running packages/sim-web. Cancelling terminates the worker. */
import loadMujoco from "@mujoco/mujoco";
import wasmUrl from "@mujoco/mujoco/mujoco.wasm?url";
import { type Replay, runPreview, type SimConfig } from "@strandbeest/sim-web";

export type SimRequest = { config: SimConfig };
export type SimMessage =
	| {
			type: "progress";
			phase: "load" | "settle" | "drive";
			fraction: number;
			simTime: number;
	  }
	| { type: "done"; replay: Replay; wallSeconds: number }
	| { type: "error"; message: string };

const post = (m: SimMessage) => self.postMessage(m);

self.onmessage = async (e: MessageEvent<SimRequest>) => {
	try {
		const t0 = performance.now();
		post({ type: "progress", phase: "load", fraction: 0, simTime: 0 });
		const mj = await loadMujoco({ locateFile: () => wasmUrl });
		const replay = await runPreview(mj, e.data.config, {
			onProgress: (p) => post({ type: "progress", ...p }),
		});
		post({
			type: "done",
			replay,
			wallSeconds: (performance.now() - t0) / 1000,
		});
	} catch (err) {
		post({
			type: "error",
			message: err instanceof Error ? err.message : String(err),
		});
	}
};
