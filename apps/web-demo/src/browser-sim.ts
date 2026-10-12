/** Client of sim.worker.ts: simulate a design on the scenes of contracts/scenes.json inside the browser (a preview, see packages/sim-web). */

import {
	type Replay,
	SCENES,
	scenarioFromDesign,
	sceneOverrides,
} from "@strandbeest/sim-web";
import type { Design } from "strandbeest-core";
import type { SimMessage } from "./sim.worker";

export interface BrowserRun {
	promise: Promise<{ replay: Replay; wallSeconds: number }>;
	cancel: () => void;
}
export type Progress = {
	phase: "load" | "settle" | "drive";
	fraction: number;
	simTime: number;
};

/** Every scene runs in the browser: the motor ones as the electric test rig, the sail ones in the chosen wind. */
export const isSail = (scene: string): boolean => !!SCENES[scene]?.sail;

export function simulateInBrowser(
	design: Design,
	scene: string,
	revolutions: number,
	windSpeed: number,
	onProgress: (p: Progress) => void,
): BrowserRun {
	const ov = sceneOverrides(scene, { revolutions, windSpeed });
	// a free walker needs about revolutions * 2 pi / omega + ramp simulated seconds; allow three times that, so a walker that is
	// blocked on an obstacle ends as stalled in about a minute instead of the scene's 40 s of simulated time
	const omega = design.drive.motor_omega_rad_s ?? 2.0;
	const expected = (revolutions * 2 * Math.PI) / omega + 1.0;
	const run = (ov.run ?? {}) as Record<string, unknown>;
	ov.run = {
		...run,
		revolutions, // the choice in the UI wins over a scene's own count
		// a sail walker's speed depends on the wind, not on the motor: it keeps the scene's own limit (30 s)
		max_time: isSail(scene)
			? run.max_time
			: Math.min(Number(run.max_time ?? 40), 3 * expected + 1),
	};
	const config = scenarioFromDesign(design, ov);
	const worker = new Worker(new URL("./sim.worker.ts", import.meta.url), {
		type: "module",
	});
	let rejectRun: (e: Error) => void = () => {};
	const promise = new Promise<{ replay: Replay; wallSeconds: number }>(
		(resolve, reject) => {
			rejectRun = reject;
			worker.onmessage = (e: MessageEvent<SimMessage>) => {
				const m = e.data;
				if (m.type === "progress") onProgress(m);
				else if (m.type === "done") {
					worker.terminate();
					resolve({ replay: m.replay, wallSeconds: m.wallSeconds });
				} else {
					worker.terminate();
					reject(new Error(m.message));
				}
			};
			worker.onerror = (e) => {
				worker.terminate();
				reject(new Error(e.message || "worker failed"));
			};
			worker.postMessage({ config });
		},
	);
	return {
		promise,
		cancel: () => {
			worker.terminate();
			rejectRun(new Error("cancelled"));
		},
	};
}
