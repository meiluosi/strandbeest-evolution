/** Port of strandbeest_sim.scenes.scene_overrides: the same overrides the web player and the agent tools use. */
import scenesFile from "../../../contracts/scenes.json";
import type { Overrides } from "./from-design";

type SceneDef = { sail?: boolean; ov: Record<string, Record<string, unknown>> };
export const SCENES = scenesFile.scenes as unknown as Record<string, SceneDef>;
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export function sceneOverrides(
	name: string,
	opts: { windSpeed?: number; revolutions?: number; frameRate?: number } = {},
): Overrides {
	const sc = SCENES[name];
	if (!sc)
		throw new Error(
			`unknown scene '${name}'; available: ${Object.keys(SCENES).sort().join(", ")}`,
		);
	const ov = clone(sc.ov);
	ov.run = {
		settle: 0.5,
		revolutions: opts.revolutions ?? 2.0,
		frame_rate: opts.frameRate ?? 30.0,
		...(ov.run ?? {}),
	};
	if (sc.sail) {
		ov.drive = { kind: "sail", ...(ov.drive ?? {}) };
		ov.wind = { ...(ov.wind ?? {}), speed: opts.windSpeed ?? 3.0 };
		ov.run = { ...ov.run, give_up_after: 6, max_time: 30 };
	}
	return ov;
}
