/** What the web replay viewer reads (apps/web-demo/src/replay-types.ts mirrors this; the Python API returns the same shape). */
export interface ReplayScene {
	bodies: string[];
	geoms: {
		body: number;
		type: "capsule" | "sphere" | "box";
		name: string;
		rgba: number[];
		foot: boolean;
		a?: number[];
		b?: number[];
		radius?: number;
		pos?: number[];
		quat?: number[];
		size?: number[];
	}[];
	obstacles: { pos: number[]; size: number[]; name: string }[];
	slope_deg: number;
}

export interface Replay {
	scene: ReplayScene;
	t: number[];
	pos: number[][][];
	quat: number[][][];
	contact: number[][];
	foot_pos: number[][][];
	foot_force: number[][][];
	foot_slip: number[][];
	com: number[][];
	series: { t: number[]; psi: number[]; x: number[]; torque: number[] };
	energy: null;
	events: never[];
	diagnosis: never[];
	metrics: Record<string, number | null>;
	stalled: boolean;
	nominal_stride_m: number | null;
	kinematic_duty: number | null;
	revolutions: number;
	info: {
		terrain: {
			kind: string;
			slope_deg: number;
			params: Record<string, unknown>;
		};
		drive: string;
		wind: { kind: string; speed: number; params: Record<string, unknown> };
		environment: { gravity: number; air_density: number };
		legs: number;
		max_torque: number | null;
	};
	/** how this replay was made: the browser preview skips the energy account, events, diagnosis and the invariant audit */
	quality: "browser-preview";
}
