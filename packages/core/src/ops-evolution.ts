import type { Design } from "./generated/design";
import type { Point } from "./geometry";
import { type LinkageSpec, solvePose } from "./linkage";
import {
	applyOp,
	designProblems,
	type Guard,
	GuardError,
	makeOp,
	OpError,
	type Operation,
} from "./ops";
import { gaussian, type Rng } from "./rng";

/**
 * E3-06: Evolution as Operation Sequences & Adaptive Mutation Operator.
 *
 * Mutations produce typed, logged, reversible edit operations (`set_param`, `add_dyad`, etc.)
 * rather than bare float vectors. Every generated candidate passes through the validity guard
 * (full-cycle assemblability, branch-flip checks, dof=1) so the population never harbours broken linkages.
 *
 * The adaptive mutation controller monitors guard violation rates and patterns,
 * dynamically shrinking perturbation steps and throttling invalid topology searches when
 * rejection rates spike, and expanding step sizes when candidate geometry is safely within
 * valid assembly regions.
 */

export interface MutateDesignOptions {
	/** probability of mutating each named parameter */
	paramMutationRate?: number;
	/** relative standard deviation for Gaussian parameter perturbation */
	paramMutationScale?: number;
	/** probability of attempting a topological mutation (add dyad) */
	topologyMutationRate?: number;
	/** bounds relative to the current parameter value [minFraction, maxFraction] */
	paramBounds?: [number, number];
	/** custom guards to protect assemblability and validity */
	guards?: Guard[];
}

export interface GuardViolation {
	opType: string;
	param?: string;
	reason: string;
	code?: string;
}

export interface MutationAttemptStats {
	attemptedOps: number;
	acceptedOps: number;
	rejectedOps: number;
	rejectionRate: number;
	violations: GuardViolation[];
	paramAttempts?: number;
	paramAccepted?: number;
	paramRejected?: number;
	topoAttempts?: number;
	topoAccepted?: number;
	topoRejected?: number;
}

export interface MutationResult {
	design: Design;
	operations: Operation[];
	stats: MutationAttemptStats;
}

/**
 * Analyze distance extrema D_min and D_max between two joints c1 and c2 across crank angles.
 */
export function computeDyadEnvelope(
	linkage: LinkageSpec,
	c1: string,
	c2: string,
	sampleCount = 16,
): { dMin: number; dMax: number; validAngles: number } | null {
	let dMin = Infinity;
	let dMax = -Infinity;
	let validAngles = 0;

	for (let i = 0; i < sampleCount; i++) {
		const theta = (2 * Math.PI * i) / sampleCount;
		const pose = solvePose(linkage, theta);
		if (pose && pose[c1] && pose[c2]) {
			const p1 = pose[c1] as Point;
			const p2 = pose[c2] as Point;
			const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
			if (d < dMin) dMin = d;
			if (d > dMax) dMax = d;
			validAngles++;
		}
	}

	if (validAngles === 0 || !Number.isFinite(dMin) || !Number.isFinite(dMax)) {
		return null;
	}
	return { dMin, dMax, validAngles };
}

/**
 * Sample dyad link lengths satisfying triangle inequalities over the envelope:
 * r1 + r2 >= D_max * (1 + epsilon)
 * |r1 - r2| <= D_min * (1 - epsilon)
 */
export function sampleDyadLengths(
	dMin: number,
	dMax: number,
	rng: Rng,
	epsilon = 0.05,
): { r1: number; r2: number } {
	const sMin = dMax * (1 + epsilon);
	const s = sMin * (1.05 + 0.35 * rng());
	const deltaMax = Math.max(0, dMin * (1 - epsilon));
	const delta = deltaMax * 0.8 * rng();

	const r1 = rng() < 0.5 ? (s + delta) / 2 : (s - delta) / 2;
	const r2 = s - r1;
	return { r1, r2 };
}

/**
 * Mutate a design by producing a sequence of typed edit operations.
 *
 * 1. If topology mutation triggers, attempts to add a valid dyad built on existing joints.
 * 2. Otherwise perturbs linkage parameters via `set_param` operations.
 * All operations pass through `applyOp` guards; if a mutation violates assemblability,
 * it is rejected safely and recorded in the attempt stats.
 */
export function mutateDesign(
	design: Design,
	rng: Rng,
	options: MutateDesignOptions = {},
): MutationResult {
	const pMutRate = options.paramMutationRate ?? 0.25;
	const pMutScale = options.paramMutationScale ?? 0.06;
	const topoRate = options.topologyMutationRate ?? 0.0;
	const [loF, hiF] = options.paramBounds ?? [0.5, 1.5];
	const guards = options.guards ?? [designProblems];

	let current = design;
	const operations: Operation[] = [];
	const violations: GuardViolation[] = [];
	let attemptedOps = 0;
	let acceptedOps = 0;
	let rejectedOps = 0;
	let paramAttempts = 0;
	let paramAccepted = 0;
	let paramRejected = 0;
	let topoAttempts = 0;
	let topoAccepted = 0;
	let topoRejected = 0;

	// 1. Topology Mutation (if enabled)
	if (topoRate > 0 && rng() < topoRate) {
		const lk = current.linkage;
		const availableCenters = ["G", "C", ...lk.joints.map((j) => j.id)];
		if (availableCenters.length >= 2) {
			attemptedOps++;
			topoAttempts++;
			// Pick two distinct centres
			const idx1 = Math.floor(rng() * availableCenters.length);
			let idx2 = Math.floor(rng() * availableCenters.length);
			if (idx2 === idx1) idx2 = (idx1 + 1) % availableCenters.length;

			const c1 = availableCenters[idx1] as string;
			const c2 = availableCenters[idx2] as string;
			const newJointId = `N${lk.joints.length + 1}`;
			const side = rng() < 0.5 ? 1 : -1;

			// Kinematic workspace envelope pre-filtering for AddDyad
			let r1: number;
			let r2: number;
			const env = computeDyadEnvelope(lk, c1, c2, 16);
			if (env && env.dMax > 0) {
				const sampled = sampleDyadLengths(env.dMin, env.dMax, rng);
				r1 = sampled.r1;
				r2 = sampled.r2;
			} else {
				const existingValues = Object.values(lk.params);
				const avgLen =
					existingValues.length > 0
						? existingValues.reduce((a, b) => a + b, 0) / existingValues.length
						: 40.0;
				r1 = avgLen * (0.8 + 0.4 * rng());
				r2 = avgLen * (0.8 + 0.4 * rng());
			}

			const p1Name = `len_${newJointId}_1`;
			const p2Name = `len_${newJointId}_2`;

			const op = makeOp(
				"add_dyad",
				{
					id: newJointId,
					centers: [c1, c2],
					radii: [p1Name, p2Name],
					side,
					params: { [p1Name]: r1, [p2Name]: r2 },
					foot: false,
				},
				{
					actor: { kind: "algorithm", id: "topology-evolution" },
					reason: `evolution topology mutation: add dyad ${newJointId}`,
				},
			);

			try {
				const applied = applyOp(current, op, guards);
				current = applied.design;
				operations.push(op);
				acceptedOps++;
				topoAccepted++;
				const stats: MutationAttemptStats = {
					attemptedOps,
					acceptedOps,
					rejectedOps,
					rejectionRate: rejectedOps / attemptedOps,
					violations,
					paramAttempts,
					paramAccepted,
					paramRejected,
					topoAttempts,
					topoAccepted,
					topoRejected,
				};
				return { design: current, operations, stats };
			} catch (err: unknown) {
				// Rejected by validity guard (e.g. geometric triangle inequality failed);
				// fall through to parameter mutation.
				rejectedOps++;
				topoRejected++;
				const reason = err instanceof Error ? err.message : String(err);
				const code =
					err instanceof GuardError
						? (err.problems[0]?.code ?? "guard_violation")
						: err instanceof OpError
							? err.code
							: "unknown";
				violations.push({
					opType: "add_dyad",
					reason,
					code,
				});
			}
		}
	}

	// 2. Continuous Parameter Mutation via set_param
	const paramNames = Object.keys(current.linkage.params).sort();
	for (const name of paramNames) {
		if (rng() < pMutRate) {
			attemptedOps++;
			paramAttempts++;
			const oldVal = current.linkage.params[name] as number;
			const delta = oldVal * pMutScale * gaussian(rng);
			const minVal = oldVal * loF;
			const maxVal = oldVal * hiF;
			const newVal = Math.min(maxVal, Math.max(minVal, oldVal + delta));

			const op = makeOp(
				"set_param",
				{ name, value: newVal },
				{
					actor: { kind: "algorithm", id: "ga" },
					reason: `evolution mutation on param ${name}`,
				},
			);

			try {
				const applied = applyOp(current, op, guards);
				current = applied.design;
				operations.push(op);
				acceptedOps++;
				paramAccepted++;
			} catch (err: unknown) {
				// If a single param perturbation violates branch-flip or closure, record violation
				rejectedOps++;
				paramRejected++;
				const reason = err instanceof Error ? err.message : String(err);
				const code =
					err instanceof GuardError
						? (err.problems[0]?.code ?? "guard_violation")
						: err instanceof OpError
							? err.code
							: "unknown";
				violations.push({
					opType: "set_param",
					param: name,
					reason,
					code,
				});
			}
		}
	}

	const stats: MutationAttemptStats = {
		attemptedOps,
		acceptedOps,
		rejectedOps,
		rejectionRate: attemptedOps > 0 ? rejectedOps / attemptedOps : 0,
		violations,
		paramAttempts,
		paramAccepted,
		paramRejected,
		topoAttempts,
		topoAccepted,
		topoRejected,
	};

	return { design: current, operations, stats };
}

export interface AdaptiveMutationConfig {
	/** Initial parameter mutation scale (default: 0.06) */
	initialParamScale?: number;
	/** Minimum parameter mutation scale (default: 0.005) */
	minParamScale?: number;
	/** Maximum parameter mutation scale (default: 0.25) */
	maxParamScale?: number;
	/** Initial topology mutation rate (default: 0.0) */
	initialTopologyRate?: number;
	/** Minimum topology mutation rate (default: 0.0) */
	minTopologyRate?: number;
	/** Maximum topology mutation rate (default: 0.4) */
	maxTopologyRate?: number;
	/** High rejection rate threshold (> this triggers scale contraction) (default: 0.45) */
	targetRejectionHigh?: number;
	/** Low rejection rate threshold (< this triggers scale expansion) (default: 0.15) */
	targetRejectionLow?: number;
	/** Multiplicative shrink factor on step scale (default: 0.85) */
	shrinkFactor?: number;
	/** Multiplicative expansion factor on step scale (default: 1.15) */
	expandFactor?: number;
	/** Moving window length for calculating rejection rate (default: 20) */
	windowSize?: number;
}

/**
 * Self-adapting mutation controller.
 *
 * Tracks guard rejection patterns (triangle inequalities, branch flips, closure ruptures)
 * and adjusts perturbation scales via Rechenberg 1/5th style dynamic feedback:
 * - If rejections exceed high threshold, contracts scale to avoid wasting candidate evaluations.
 * - If rejections are consistently low, safely expands scale to accelerate exploratory coverage.
 */
export class AdaptiveMutationController {
	private paramScale: number;
	private topologyRate: number;
	private readonly minParamScale: number;
	private readonly maxParamScale: number;
	private readonly minTopologyRate: number;
	private readonly maxTopologyRate: number;
	private readonly targetRejectionHigh: number;
	private readonly targetRejectionLow: number;
	private readonly shrinkFactor: number;
	private readonly expandFactor: number;
	private readonly windowSize: number;

	private history: Array<{
		accepted: number;
		rejected: number;
		paramAccepted: number;
		paramRejected: number;
		topoAccepted: number;
		topoRejected: number;
	}> = [];
	private violationCounts: Record<string, number> = {};
	private paramViolationCounts: Record<string, number> = {};

	private totalAttempts = 0;
	private totalAccepted = 0;
	private totalRejected = 0;
	private totalParamAttempts = 0;
	private totalParamAccepted = 0;
	private totalParamRejected = 0;
	private totalTopoAttempts = 0;
	private totalTopoAccepted = 0;
	private totalTopoRejected = 0;

	constructor(config: AdaptiveMutationConfig = {}) {
		this.paramScale = config.initialParamScale ?? 0.06;
		this.minParamScale = config.minParamScale ?? 0.005;
		this.maxParamScale = config.maxParamScale ?? 0.25;

		this.topologyRate = config.initialTopologyRate ?? 0.0;
		this.minTopologyRate = config.minTopologyRate ?? 0.0;
		this.maxTopologyRate = config.maxTopologyRate ?? 0.4;

		this.targetRejectionHigh = config.targetRejectionHigh ?? 0.45;
		this.targetRejectionLow = config.targetRejectionLow ?? 0.15;
		this.shrinkFactor = config.shrinkFactor ?? 0.85;
		this.expandFactor = config.expandFactor ?? 1.15;
		this.windowSize = config.windowSize ?? 20;
	}

	getParamScale(): number {
		return this.paramScale;
	}

	getTopologyRate(): number {
		return this.topologyRate;
	}

	recordStats(stats: MutationAttemptStats): void {
		if (stats.attemptedOps === 0) return;

		this.totalAttempts += stats.attemptedOps;
		this.totalAccepted += stats.acceptedOps;
		this.totalRejected += stats.rejectedOps;

		for (const v of stats.violations) {
			const code = v.code ?? "unknown";
			this.violationCounts[code] = (this.violationCounts[code] ?? 0) + 1;
			if (v.param) {
				this.paramViolationCounts[v.param] =
					(this.paramViolationCounts[v.param] ?? 0) + 1;
			}
		}

		// Decouple topology vs continuous parameter statistics
		const topoRej =
			stats.topoRejected ??
			stats.violations.filter((v) => v.opType === "add_dyad").length;
		const topoAtt =
			stats.topoAttempts ??
			(stats.topoAccepted !== undefined
				? stats.topoAccepted + topoRej
				: topoRej > 0
					? topoRej
					: stats.violations.some((v) => v.opType === "add_dyad")
						? 1
						: 0);
		const topoAcc = stats.topoAccepted ?? Math.max(0, topoAtt - topoRej);

		const paramRej =
			stats.paramRejected ??
			stats.violations.filter(
				(v) =>
					v.opType === "set_param" ||
					(v.opType !== "add_dyad" && Boolean(v.param)),
			).length;
		const paramAtt =
			stats.paramAttempts ?? Math.max(0, stats.attemptedOps - topoAtt);
		const paramAcc = stats.paramAccepted ?? Math.max(0, paramAtt - paramRej);

		this.totalParamAttempts += paramAtt;
		this.totalParamAccepted += paramAcc;
		this.totalParamRejected += paramRej;

		this.totalTopoAttempts += topoAtt;
		this.totalTopoAccepted += topoAcc;
		this.totalTopoRejected += topoRej;

		this.history.push({
			accepted: stats.acceptedOps,
			rejected: stats.rejectedOps,
			paramAccepted: paramAcc,
			paramRejected: paramRej,
			topoAccepted: topoAcc,
			topoRejected: topoRej,
		});

		if (this.history.length > this.windowSize) {
			this.history.shift();
		}

		// 1. Continuous paramScale updated ONLY based on parameter mutation success/failure
		const winParamAccepted = this.history.reduce(
			(sum, h) => sum + h.paramAccepted,
			0,
		);
		const winParamRejected = this.history.reduce(
			(sum, h) => sum + h.paramRejected,
			0,
		);
		const winParamTotal = winParamAccepted + winParamRejected;

		if (winParamTotal >= 5) {
			const paramRejRate = winParamRejected / winParamTotal;
			if (paramRejRate > this.targetRejectionHigh) {
				this.paramScale = Math.max(
					this.minParamScale,
					this.paramScale * this.shrinkFactor,
				);
			} else if (paramRejRate < this.targetRejectionLow) {
				this.paramScale = Math.min(
					this.maxParamScale,
					this.paramScale * this.expandFactor,
				);
			}
		}

		// 2. Topology mutation rate updated ONLY based on topology mutation success/failure
		const winTopoAccepted = this.history.reduce(
			(sum, h) => sum + h.topoAccepted,
			0,
		);
		const winTopoRejected = this.history.reduce(
			(sum, h) => sum + h.topoRejected,
			0,
		);
		const winTopoTotal = winTopoAccepted + winTopoRejected;

		if (winTopoTotal >= 1) {
			const topoRejRate = winTopoRejected / winTopoTotal;
			if (topoRejRate > this.targetRejectionHigh) {
				this.topologyRate = Math.max(
					this.minTopologyRate,
					this.topologyRate * this.shrinkFactor,
				);
			} else if (topoRejRate < this.targetRejectionLow && winTopoTotal >= 3) {
				this.topologyRate = Math.min(
					this.maxTopologyRate,
					this.topologyRate * this.expandFactor,
				);
			}
		}
	}

	mutate(
		design: Design,
		rng: Rng,
		baseOptions: Omit<
			MutateDesignOptions,
			"paramMutationScale" | "topologyMutationRate"
		> = {},
	): MutationResult {
		const result = mutateDesign(design, rng, {
			...baseOptions,
			paramMutationScale: this.paramScale,
			topologyMutationRate: this.topologyRate,
		});
		this.recordStats(result.stats);
		return result;
	}

	summary(): {
		totalAttempts: number;
		totalAccepted: number;
		totalRejected: number;
		overallRejectionRate: number;
		totalParamAttempts: number;
		totalParamAccepted: number;
		totalParamRejected: number;
		paramRejectionRate: number;
		totalTopoAttempts: number;
		totalTopoAccepted: number;
		totalTopoRejected: number;
		topoRejectionRate: number;
		currentParamScale: number;
		currentTopologyRate: number;
		violationsByCode: Record<string, number>;
		violationsByParam: Record<string, number>;
	} {
		return {
			totalAttempts: this.totalAttempts,
			totalAccepted: this.totalAccepted,
			totalRejected: this.totalRejected,
			overallRejectionRate:
				this.totalAttempts > 0 ? this.totalRejected / this.totalAttempts : 0,
			totalParamAttempts: this.totalParamAttempts,
			totalParamAccepted: this.totalParamAccepted,
			totalParamRejected: this.totalParamRejected,
			paramRejectionRate:
				this.totalParamAttempts > 0
					? this.totalParamRejected / this.totalParamAttempts
					: 0,
			totalTopoAttempts: this.totalTopoAttempts,
			totalTopoAccepted: this.totalTopoAccepted,
			totalTopoRejected: this.totalTopoRejected,
			topoRejectionRate:
				this.totalTopoAttempts > 0
					? this.totalTopoRejected / this.totalTopoAttempts
					: 0,
			currentParamScale: this.paramScale,
			currentTopologyRate: this.topologyRate,
			violationsByCode: { ...this.violationCounts },
			violationsByParam: { ...this.paramViolationCounts },
		};
	}
}

export function createAdaptiveMutationController(
	config: AdaptiveMutationConfig = {},
): AdaptiveMutationController {
	return new AdaptiveMutationController(config);
}
