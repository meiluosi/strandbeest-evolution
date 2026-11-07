import type { Point } from "./geometry";
import { kinematicsKernel } from "./kernel";

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

export function gaitMetrics(foot: Point[], tol = 0.015): GaitMetrics {
	return kinematicsKernel().gaitMetrics(foot, tol);
}

/** Normalise a loop: centre on its bounding box and scale so its width is 1. */
function normalise(path: Point[]): Point[] {
	if (path.length === 0) return [];
	let minX = Number.POSITIVE_INFINITY;
	let maxX = Number.NEGATIVE_INFINITY;
	let minY = Number.POSITIVE_INFINITY;
	let maxY = Number.NEGATIVE_INFINITY;
	for (const p of path) {
		if (p.x < minX) minX = p.x;
		if (p.x > maxX) maxX = p.x;
		if (p.y < minY) minY = p.y;
		if (p.y > maxY) maxY = p.y;
	}
	const w = maxX - minX || 1;
	const cx = (maxX + minX) / 2;
	const cy = (maxY + minY) / 2;
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
