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
	nominal_stride_m: number | null;
	kinematic_duty: number | null;
	revolutions: number;
	info: {
		terrain: {
			kind: string;
			slope_deg: number;
			params: Record<string, number>;
		};
		drive: string;
		wind: { kind: string; speed: number; params: Record<string, number> };
		environment: { gravity: number; air_density: number };
		legs: number;
		max_torque: number | null;
	};
};

export interface Overlays {
	forces: boolean;
	slip: boolean;
	com: boolean;
}

/** Index of the recorded frame closest to time `t` (seconds since the start of driving). */
export function frameAt(r: Replay, t: number): number {
	const n = r.t.length;
	if (n < 2) return 0;
	const t0 = r.t[0] as number;
	const dt = ((r.t[n - 1] as number) - t0) / (n - 1);
	return Math.max(0, Math.min(n - 1, Math.round((t - t0) / dt)));
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
