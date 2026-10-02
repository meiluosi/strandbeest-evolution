import { JANSEN_PARAM_NAMES, type JansenParams, jansenSpec } from "./jansen";
import { trace } from "./linkage";
import { type GaitMetrics, gaitMetrics } from "./metrics";

export type Fitness = (genome: number[]) => number;

export function genomeToParams(genome: number[]): JansenParams {
	const p = {} as JansenParams;
	JANSEN_PARAM_NAMES.forEach((name, i) => {
		p[name] = genome[i] as number;
	});
	return p;
}

export function paramsToGenome(p: JansenParams): number[] {
	return JANSEN_PARAM_NAMES.map((n) => p[n]);
}

/** A leg whose foot jumps more than this fraction of its path width between samples flipped branch. */
const MAX_STEP_RATIO = 0.25;

/**
 * Metrics for a genome, or null if the leg is not physically sensible:
 * cannot assemble, flips branch, or its foot rises above the hip pivot (G, the origin) —
 * without that last rule the GA "wins" by swinging the foot through the body.
 */
export function legMetrics(genome: number[]): GaitMetrics | null {
	const t = trace(jansenSpec(genomeToParams(genome)), 90);
	if (!t.assembled) return null;
	const m = gaitMetrics(t.foot);
	if (m.width <= 0 || t.maxStep > MAX_STEP_RATIO * m.width) return null;
	if (t.foot.some((p) => p.y >= 0)) return null;
	return m;
}

/**
 * v1: a walking gait needs a flat ground stroke AND a real swing phase, so:
 * - lift below 15% of width is rejected (a foot that only slides is not a leg),
 * - duty is credited only up to 0.6 (the rest of the cycle must be the raised return),
 * - score = min(duty, 0.6) * (1 + min(lift/width, 0.4)) * (strokeLength/width).
 * These thresholds are design choices, not Jansen's; see docs/RESEARCH-NOTES.md.
 */
export const fitnessFlatStroke: Fitness = (genome) => {
	const m = legMetrics(genome);
	if (!m) return Number.NEGATIVE_INFINITY;
	const ratio = m.lift / m.width;
	if (ratio < 0.15) return ratio - 1;
	return (
		Math.min(m.duty, 0.6) *
		(1 + Math.min(ratio, 0.4)) *
		(m.strokeLength / m.width)
	);
};

/** v2: maximise step height while keeping at least `minDuty` of the cycle on the ground. For obstacle-crossing legs. */
export function fitnessHighStep(minDuty = 0.35): Fitness {
	return (genome) => {
		const m = legMetrics(genome);
		if (!m) return Number.NEGATIVE_INFINITY;
		if (m.duty < minDuty) return m.duty - minDuty - 1;
		return m.lift / m.width;
	};
}
