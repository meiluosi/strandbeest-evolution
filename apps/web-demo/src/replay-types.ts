import type {
	AuditObservationDocument,
	SimulationAuditReport,
} from "@strandbeest/sim-web";

/** What GET /runs/{id}/replay returns (see apps/api app.py). Positions are MuJoCo world frame: x forward, y lateral, z up. */
export type Scene = {
	bodies: string[];
	geoms: {
		body: number;
		type: "capsule" | "sphere" | "box";
		rgba: number[];
		foot: boolean;
		a?: number[];
		b?: number[];
		radius?: number;
		pos?: number[];
		quat?: number[];
		size?: number[];
	}[];
	obstacles: { pos: number[]; size: number[] }[];
	slope_deg: number;
	water_level_m?: number | null;
};

export type RunEvent = {
	t: number;
	kind: string;
	leg?: number;
	detail?: Record<string, number>;
};
export type Diagnosis = {
	code: string;
	severity: "info" | "warning" | "error";
	message: string;
	evidence: Record<string, number | string | null>;
};

export type Replay = {
	scene: Scene;
	t: number[];
	pos: number[][][];
	quat: number[][][];
	contact: number[][];
	foot_pos?: number[][][];
	foot_force?: number[][][];
	foot_slip?: number[][];
	com?: number[][];
	series: { t: number[]; psi: number[]; x: number[]; torque: number[] };
	energy: Record<string, number[]> | null;
	events: RunEvent[];
	diagnosis: Diagnosis[];
	metrics: Record<string, number | null>;
	stalled: boolean;
	audit?: SimulationAuditReport;
	audit_observation?: AuditObservationDocument;
	nominal_stride_m: number | null;
	kinematic_duty: number | null;
	revolutions: number;
	pneumatics?: {
		bottle_pressure_pa?: number[];
		bottle_pressure?: number[];
		p_bottle?: number[];
		p_cyl?: number[];
		feeler_vacuum_pa?: number[];
		feeler_vacuum?: number[];
		valve_state?: number[];
		step_count?: number[];
		anchor_deployed?: number[];
		anchor_depth?: number[];
	};
	info: {
		terrain: {
			kind: string;
			slope_deg: number;
			params: Record<string, number>;
			water_level_m?: number | null;
		};
		drive: string;
		wind: { kind: string; speed: number; params: Record<string, number> };
		environment: { gravity: number; air_density: number };
		legs: number;
		max_torque: number | null;
		pneumatics?: Record<string, any>;
	};
};

export interface Overlays {
	forces: boolean;
	slip: boolean;
	com: boolean;
	wind?: boolean;
	trails?: boolean;
	pvc?: boolean;
	pneumatics?: boolean;
}

/** Index of the recorded frame closest to time `t` (seconds since the start of driving). */
export function frameAt(r: Replay, t: number): number {
	const n = r.t.length;
	if (n < 2) return 0;
	const t0 = r.t[0] as number;
	const dt = ((r.t[n - 1] as number) - t0) / (n - 1);
	return Math.max(0, Math.min(n - 1, Math.round((t - t0) / dt)));
}

/** Find surrounding keyframe indices k0, k1 and fractional interpolation alpha in [0, 1] for time `t`. */
export function findKeyframes(
	times: number[],
	t: number,
): { k0: number; k1: number; alpha: number } {
	const n = times.length;
	if (n === 0) return { k0: 0, k1: 0, alpha: 0 };
	if (n === 1) return { k0: 0, k1: 0, alpha: 0 };
	const t0 = times[0] as number;
	if (t <= t0) return { k0: 0, k1: 0, alpha: 0 };
	const tEnd = times[n - 1] as number;
	if (t >= tEnd) return { k0: n - 1, k1: n - 1, alpha: 0 };

	let low = 0;
	let high = n - 1;
	while (low <= high) {
		const mid = (low + high) >> 1;
		if ((times[mid] as number) <= t) {
			low = mid + 1;
		} else {
			high = mid - 1;
		}
	}
	const k0 = Math.max(0, Math.min(n - 2, high));
	const k1 = k0 + 1;
	const tk0 = times[k0] as number;
	const tk1 = times[k1] as number;
	const dt = tk1 - tk0;
	const alpha = dt > 1e-6 ? Math.max(0, Math.min(1, (t - tk0) / dt)) : 0;
	return { k0, k1, alpha };
}

/** Convex hull (monotone chain) of 2D points, counter-clockwise. */
export function hull(points: [number, number][]): [number, number][] {
	const p = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
	if (p.length < 3) return p;
	const cross = (o: number[], a: number[], b: number[]) =>
		((a[0] as number) - (o[0] as number)) *
			((b[1] as number) - (o[1] as number)) -
		((a[1] as number) - (o[1] as number)) *
			((b[0] as number) - (o[0] as number));
	const lower: [number, number][] = [];
	for (const q of p) {
		while (
			lower.length >= 2 &&
			cross(
				lower[lower.length - 2] as number[],
				lower[lower.length - 1] as number[],
				q,
			) <= 0
		)
			lower.pop();
		lower.push(q);
	}
	const upper: [number, number][] = [];
	for (const q of [...p].reverse()) {
		while (
			upper.length >= 2 &&
			cross(
				upper[upper.length - 2] as number[],
				upper[upper.length - 1] as number[],
				q,
			) <= 0
		)
			upper.pop();
		upper.push(q);
	}
	return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

export function insidePolygon(
	pt: [number, number],
	poly: [number, number][],
): boolean {
	let inside = false;
	for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
		const [xi, yi] = poly[i] as [number, number];
		const [xj, yj] = poly[j] as [number, number];
		if (
			yi > pt[1] !== yj > pt[1] &&
			pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi
		)
			inside = !inside;
	}
	return inside;
}

/** Index of the frame where two runs differ most, comparing body positions at the same time; null when frames are missing. */
export function largestDifference(
	a: Replay,
	b: Replay,
): { t: number; distance: number } | null {
	const n = Math.min(a.t.length, 400);
	let best: { t: number; distance: number } | null = null;
	for (let i = 0; i < n; i++) {
		const ta = a.t[
			Math.round((i / Math.max(n - 1, 1)) * (a.t.length - 1))
		] as number;
		const fa = a.pos[frameAt(a, ta)];
		const fb = b.pos[frameAt(b, ta)];
		if (!fa || !fb) continue;
		let sum = 0;
		const m = Math.min(fa.length, fb.length);
		for (let k = 0; k < m; k++) {
			const p = fa[k] as number[];
			const q = fb[k] as number[];
			sum += Math.hypot(
				(p[0] as number) - (q[0] as number),
				(p[1] as number) - (q[1] as number),
				(p[2] as number) - (q[2] as number),
			);
		}
		const d = sum / Math.max(m, 1);
		if (!best || d > best.distance) best = { t: ta, distance: d };
	}
	return best;
}
