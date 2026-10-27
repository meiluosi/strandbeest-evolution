import type { Design } from "./generated/design";
import {
	applyOp,
	designProblems,
	type Guard,
	makeOp,
	type Operation,
} from "./ops";
import { gaussian, type Rng } from "./rng";

/**
 * E3-06: Evolution as Operation Sequences.
 *
 * Mutations produce typed, logged, reversible edit operations (`set_param`, `add_dyad`, etc.)
 * rather than bare float vectors. Every generated candidate passes through the validity guard
 * (full-cycle assemblability, branch-flip checks, dof=1) so the population never harbours broken linkages.
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

export interface MutationResult {
	design: Design;
	operations: Operation[];
}

/**
 * Mutate a design by producing a sequence of typed edit operations.
 *
 * 1. If topology mutation triggers, attempts to add a valid dyad built on existing joints.
 * 2. Otherwise perturbs linkage parameters via `set_param` operations.
 * All operations pass through `applyOp` guards; if a mutation violates assemblability,
 * it is rejected safely.
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

	// 1. Topology Mutation (if enabled)
	if (topoRate > 0 && rng() < topoRate) {
		const lk = current.linkage;
		const availableCenters = ["G", "C", ...lk.joints.map((j) => j.id)];
		if (availableCenters.length >= 2) {
			// Pick two distinct centres
			const idx1 = Math.floor(rng() * availableCenters.length);
			let idx2 = Math.floor(rng() * availableCenters.length);
			if (idx2 === idx1) idx2 = (idx1 + 1) % availableCenters.length;

			const c1 = availableCenters[idx1] as string;
			const c2 = availableCenters[idx2] as string;
			const newJointId = `N${lk.joints.length + 1}`;
			const side = rng() < 0.5 ? 1 : -1;

			// Pick reasonable radii based on average link length
			const existingValues = Object.values(lk.params);
			const avgLen =
				existingValues.length > 0
					? existingValues.reduce((a, b) => a + b, 0) / existingValues.length
					: 40.0;
			const r1 = avgLen * (0.8 + 0.4 * rng());
			const r2 = avgLen * (0.8 + 0.4 * rng());

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
				return { design: current, operations };
			} catch {
				// Rejected by validity guard (e.g. geometric triangle inequality failed);
				// fall through to parameter mutation.
			}
		}
	}

	// 2. Continuous Parameter Mutation via set_param
	const paramNames = Object.keys(current.linkage.params).sort();
	for (const name of paramNames) {
		if (rng() < pMutRate) {
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
			} catch {
				// If a single param perturbation violates branch-flip or closure, ignore this step
			}
		}
	}

	return { design: current, operations };
}
