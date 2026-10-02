import { JANSEN_PARAM_NAMES, type JansenParams, jansenSpec } from "./jansen";
import { solvePose, trace } from "./linkage";
import { type GaitMetrics, gaitMetrics, pathDistance } from "./metrics";

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

/** Fitness values at or below this mean the leg is infeasible (cannot assemble, flips, or hits the body). */
export const INFEASIBLE = -4;

/**
 * Graded penalty for an infeasible leg, always in [-10, -4): the closer it is to a working leg, the higher.
 * A flat -Infinity gives a GA nothing to climb when random lengths almost never assemble.
 * Returns null if the leg is feasible.
 */
export function infeasibility(genome: number[]): number | null {
	const spec = jansenSpec(genomeToParams(genome));
	const probes = 24;
	let ok = 0;
	for (let i = 0; i < probes; i++)
		if (solvePose(spec, (2 * Math.PI * i) / probes)) ok++;
	if (ok < probes) return -10 + 5 * (ok / probes); // [-10, -5)
	const t = trace(spec, 90);
	const m = gaitMetrics(t.foot);
	const belowHip = t.foot.filter((p) => p.y < 0).length / t.foot.length;
	const flipped = m.width <= 0 || t.maxStep > MAX_STEP_RATIO * m.width;
	if (belowHip < 1 || flipped)
		return -5 + 0.9 * belowHip - (flipped ? 0.05 : 0); // [-5, -4.1]
	return null;
}

/**
 * Metrics for a genome, or null if the leg is not physically sensible:
 * cannot assemble, flips branch, or its foot rises above the hip pivot (G, the origin) —
 * without that last rule the GA "wins" by swinging the foot through the body.
 */
export function legMetrics(genome: number[]): GaitMetrics | null {
	if (infeasibility(genome) !== null) return null;
	return gaitMetrics(trace(jansenSpec(genomeToParams(genome)), 90).foot);
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
	if (!m) return infeasibility(genome) as number;
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
		if (!m) return infeasibility(genome) as number;
		if (m.duty < minDuty) return m.duty - minDuty - 1;
		return m.lift / m.width;
	};
}

/** Hip-to-foot distance averaged over the cycle: a size scale for the leg. */
function legScale(foot: { x: number; y: number }[]): number {
	return foot.reduce((s, p) => s + Math.hypot(p.x, p.y), 0) / foot.length;
}

/**
 * Inverse problem: find lengths whose foot loop has the same shape as `target`.
 * Used to test whether the GA can recover a known design (e.g. Jansen's) from random starts.
 */
export function fitnessMatchPath(target: { x: number; y: number }[]): Fitness {
	return (genome) => {
		const bad = infeasibility(genome);
		if (bad !== null) return bad;
		const t = trace(jansenSpec(genomeToParams(genome)), target.length);
		return t.assembled ? -pathDistance(t.foot, target) : -10;
	};
}

/**
 * Speed proxy: ground stroke length per crank revolution, relative to leg size, given a real swing phase.
 * Kinematic only — says nothing about torque, slip or wind.
 */
export function fitnessSpeed(minDuty = 0.4, minLiftRatio = 0.15): Fitness {
	return (genome) => {
		const m = legMetrics(genome);
		if (!m) return infeasibility(genome) as number;
		if (m.lift / m.width < minLiftRatio) return m.lift / m.width - 1;
		if (m.duty < minDuty) return m.duty - minDuty - 1;
		const t = trace(jansenSpec(genomeToParams(genome)), 90);
		return m.strokeLength / legScale(t.foot);
	};
}

/**
 * Efficiency proxy: how much of the foot's travel is useful ground stroke versus lifting.
 * strokeLength / (strokeLength + 2 * lift), with the same walking constraints. A proxy for wasted vertical motion,
 * NOT a measured energy cost (that needs the M4 dynamics model).
 */
export function fitnessEfficiencyProxy(
	minDuty = 0.4,
	minLiftRatio = 0.15,
): Fitness {
	return (genome) => {
		const m = legMetrics(genome);
		if (!m) return infeasibility(genome) as number;
		if (m.lift / m.width < minLiftRatio) return m.lift / m.width - 1;
		if (m.duty < minDuty) return m.duty - minDuty - 1;
		return m.strokeLength / (m.strokeLength + 2 * m.lift);
	};
}
