import type { Point } from "./geometry";
import { type LinkageSpec, trace } from "./linkage";

export interface LegPhase {
	/** crank phase offset in radians */
	phase: number;
}

/** `n` legs on a shared crankshaft with evenly spaced phases (the Strandbeest uses many such legs). */
export function evenPhases(n: number): LegPhase[] {
	return Array.from({ length: n }, (_, i) => ({
		phase: (2 * Math.PI * i) / n,
	}));
}

/**
 * Foot position of every leg at each sample of one crank revolution.
 * result[leg][k] = foot of that leg when the crank is at angle k/samples*2π.
 */
export function multiLegFeet(
	spec: LinkageSpec,
	legs: LegPhase[],
	samples = 120,
): Point[][] | null {
	const base = trace(spec, samples);
	if (!base.assembled) return null;
	return legs.map((leg) => {
		const shift = Math.round((leg.phase / (2 * Math.PI)) * samples);
		return base.foot.map(
			(_, k) =>
				base.foot[(((k + shift) % samples) + samples) % samples] as Point,
		);
	});
}

/**
 * Per crank sample, how many feet are within `tol` (a fraction of path width) of the lowest foot position:
 * a kinematic proxy for support. A stable walker wants this >= 3 at all times for a tripod-like base
 * (counted across both sides of the body, i.e. pass legs from both sides).
 */
export function groundContactCounts(feet: Point[][], tol = 0.015): number[] {
	if (feet.length === 0 || !feet[0] || feet[0].length === 0) return [];
	let minX = Number.POSITIVE_INFINITY;
	let maxX = Number.NEGATIVE_INFINITY;
	let minY = Number.POSITIVE_INFINITY;
	let maxY = Number.NEGATIVE_INFINITY;
	for (const leg of feet) {
		for (const p of leg) {
			if (p.x < minX) minX = p.x;
			if (p.x > maxX) maxX = p.x;
			if (p.y < minY) minY = p.y;
			if (p.y > maxY) maxY = p.y;
		}
	}
	const lo = minY;
	const width = maxX - minX;
	const samples = feet[0].length;
	return Array.from({ length: samples }, (_, k) =>
		feet.reduce(
			(c, leg) => c + ((leg[k] as Point)?.y <= lo + tol * width ? 1 : 0),
			0,
		),
	);
}
