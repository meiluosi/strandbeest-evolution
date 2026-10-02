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
