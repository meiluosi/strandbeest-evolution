import type { Point } from "./geometry";

export interface GaitMetrics {
	/** horizontal extent of the whole foot loop */
	width: number;
	/** vertical extent of the foot loop (step height) */
	lift: number;
	/** x-span covered during the flat ground stroke */
	strokeLength: number;
	/** fraction of the cycle spent in the flat ground stroke (duty factor) */
	duty: number;
}

/**
 * Longest contiguous (cyclic) arc of the loop whose y stays within `tol * width` of the lowest point.
 * The tolerance scales with width, not lift, so a taller loop does not get a looser definition of "flat".
 * y is up, so the ground stroke is the bottom of the loop.
 */
export function gaitMetrics(foot: Point[], tol = 0.015): GaitMetrics {
	const n = foot.length;
	const ys = foot.map((p) => p.y);
	const xs = foot.map((p) => p.x);
	const lo = Math.min(...ys);
	const lift = Math.max(...ys) - lo;
	const width = Math.max(...xs) - Math.min(...xs);
	const limit = lo + tol * width;
	const onGround = foot.map((p) => p.y <= limit);
	if (onGround.every(Boolean))
		return { width, lift, strokeLength: width, duty: 1 };

	let best = 0;
	let bestStart = 0;
	let run = 0;
	let runStart = 0;
	// walk the loop twice so a run crossing index 0 is counted whole
	for (let i = 0; i < 2 * n; i++) {
		if (onGround[i % n]) {
			if (run === 0) runStart = i;
			run++;
			if (run > best && run <= n) {
				best = run;
				bestStart = runStart;
			}
		} else run = 0;
	}
	let minX = Number.POSITIVE_INFINITY;
	let maxX = Number.NEGATIVE_INFINITY;
	for (let i = 0; i < best; i++) {
		const x = (foot[(bestStart + i) % n] as Point).x;
		minX = Math.min(minX, x);
		maxX = Math.max(maxX, x);
	}
	return {
		width,
		lift,
		strokeLength: best > 0 ? maxX - minX : 0,
		duty: best / n,
	};
}

/** Normalise a loop: centre on its bounding box and scale so its width is 1. */
function normalise(path: Point[]): Point[] {
	const xs = path.map((p) => p.x);
	const ys = path.map((p) => p.y);
	const w = Math.max(...xs) - Math.min(...xs) || 1;
	const cx = (Math.max(...xs) + Math.min(...xs)) / 2;
	const cy = (Math.max(...ys) + Math.min(...ys)) / 2;
	return path.map((p) => ({ x: (p.x - cx) / w, y: (p.y - cy) / w }));
}

function meanNearest(a: Point[], b: Point[]): number {
	let sum = 0;
	for (const p of a) {
		let best = Number.POSITIVE_INFINITY;
		for (const q of b)
			best = Math.min(best, (p.x - q.x) ** 2 + (p.y - q.y) ** 2);
		sum += Math.sqrt(best);
	}
	return sum / a.length;
}

/**
 * Scale- and translation-invariant shape distance between two foot loops
 * (symmetric mean nearest-point distance, in units of path width). 0 = same shape.
 * Orientation is NOT normalised: a mirrored or rotated loop counts as different.
 */
export function pathDistance(a: Point[], b: Point[]): number {
	const na = normalise(a);
	const nb = normalise(b);
	return (meanNearest(na, nb) + meanNearest(nb, na)) / 2;
}
