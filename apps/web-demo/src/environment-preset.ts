import type { Replay } from "./replay-types";

export type EnvironmentKind = "earth" | "moon" | "mars" | "titan" | "venus";

export interface EnvironmentPreset {
	kind: EnvironmentKind;
	skyTop: number;
	skyHorizon: number;
	sand: number;
	wetSand: number;
	waterDeep: number;
	waterLight: number;
	moon: number;
	sea: boolean;
	moonDisc: boolean;
	stars: boolean;
}

const PRESETS: Record<EnvironmentKind, EnvironmentPreset> = {
	earth: {
		kind: "earth",
		skyTop: 0x07111f,
		skyHorizon: 0x294253,
		sand: 0x766c5e,
		wetSand: 0x283d46,
		waterDeep: 0x071d2b,
		waterLight: 0x2d6672,
		moon: 0xffedca,
		sea: true,
		moonDisc: true,
		stars: true,
	},
	moon: {
		kind: "moon",
		skyTop: 0x010207,
		skyHorizon: 0x111522,
		sand: 0x65666b,
		wetSand: 0x45474e,
		waterDeep: 0x111522,
		waterLight: 0x111522,
		moon: 0xa8d8ff,
		sea: false,
		moonDisc: true,
		stars: true,
	},
	mars: {
		kind: "mars",
		skyTop: 0x1b1018,
		skyHorizon: 0x9a5848,
		sand: 0x805346,
		wetSand: 0x533a36,
		waterDeep: 0x1b1018,
		waterLight: 0x1b1018,
		moon: 0xe3c3a4,
		sea: false,
		moonDisc: true,
		stars: true,
	},
	titan: {
		kind: "titan",
		skyTop: 0x211a19,
		skyHorizon: 0xb47b46,
		sand: 0x66564a,
		wetSand: 0x403b37,
		waterDeep: 0x211a19,
		waterLight: 0x211a19,
		moon: 0xe3c3a4,
		sea: false,
		moonDisc: false,
		stars: false,
	},
	venus: {
		kind: "venus",
		skyTop: 0x38251d,
		skyHorizon: 0xd39a5e,
		sand: 0x79604d,
		wetSand: 0x51443a,
		waterDeep: 0x38251d,
		waterLight: 0x38251d,
		moon: 0xffd8a3,
		sea: false,
		moonDisc: false,
		stars: false,
	},
};

export function environmentForReplay(replay: Replay): EnvironmentPreset {
	const { gravity, air_density: airDensity } = replay.info.environment;
	if (gravity < 2 && airDensity < 0.01) return PRESETS.moon;
	if (gravity < 2) return PRESETS.titan;
	if (gravity < 5) return PRESETS.mars;
	if (gravity > 7 && airDensity > 10) return PRESETS.venus;
	return PRESETS.earth;
}
