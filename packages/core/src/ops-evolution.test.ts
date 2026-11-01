import { describe, expect, it } from "vitest";
import { defaultDesign } from "./design";
import { applyOp, designProblems, replay } from "./ops";
import {
	AdaptiveMutationController,
	computeDyadEnvelope,
	createAdaptiveMutationController,
	mutateDesign,
	sampleDyadLengths,
} from "./ops-evolution";
import { createRng } from "./rng";

describe("E3-06: operations-driven evolution and mutations", () => {
	it("parameter mutations produce valid set_param operations that replay cleanly", () => {
		const base = defaultDesign();
		const rng = createRng(42);

		const {
			design: mutated,
			operations,
			stats,
		} = mutateDesign(base, rng, {
			paramMutationRate: 0.5,
			paramMutationScale: 0.05,
			topologyMutationRate: 0.0,
		});

		expect(operations.length).toBeGreaterThan(0);
		for (const op of operations) {
			expect(op.type).toBe("set_param");
			expect(op.actor.kind).toBe("algorithm");
		}

		// Stats correctly account for operations
		expect(stats.attemptedOps).toBeGreaterThan(0);
		expect(stats.acceptedOps).toBe(operations.length);
		expect(stats.attemptedOps).toBe(stats.acceptedOps + stats.rejectedOps);

		// Validity guard: the mutated design has 0 kinematic errors
		const problems = designProblems(mutated);
		expect(problems.filter((p) => p.level === "error")).toHaveLength(0);

		// Replaying the operations on base yields identical design
		const replayed = replay(base, operations);
		expect(replayed).toEqual(mutated);
	});

	it("deterministic behavior with fixed RNG seed", () => {
		const base = defaultDesign();
		const res1 = mutateDesign(base, createRng(12345), {
			paramMutationRate: 0.3,
		});
		const res2 = mutateDesign(base, createRng(12345), {
			paramMutationRate: 0.3,
		});

		expect(res1.operations.map((o) => o.args)).toEqual(
			res2.operations.map((o) => o.args),
		);
		expect(res1.design).toEqual(res2.design);
	});

	it("topology mutation creates a valid add_dyad when successful", () => {
		const base = defaultDesign();
		let dyadAdded = false;

		// Try multiple seeds to find an assemblable topology candidate
		for (let seed = 1; seed <= 50; seed++) {
			const rng = createRng(seed);
			const { design: mutated, operations } = mutateDesign(base, rng, {
				paramMutationRate: 0.0,
				topologyMutationRate: 1.0,
			});

			const addOp = operations.find((o) => o.type === "add_dyad");
			if (addOp) {
				dyadAdded = true;
				expect(mutated.linkage.joints.length).toBe(
					base.linkage.joints.length + 1,
				);
				// Full cycle assemblability check
				const errors = designProblems(mutated).filter(
					(p) => p.level === "error",
				);
				expect(errors).toHaveLength(0);
				break;
			}
		}

		expect(dyadAdded).toBe(true);
	});

	it("adaptive controller contracts scale when rejection rate is high", () => {
		const base = defaultDesign();
		const ctrl = createAdaptiveMutationController({
			initialParamScale: 0.15,
			shrinkFactor: 0.8,
			targetRejectionHigh: 0.3,
			windowSize: 5,
		});

		const initialScale = ctrl.getParamScale();

		// Simulate repeated mutations with aggressive perturbations that trigger rejections
		const rng = createRng(999);
		for (let i = 0; i < 20; i++) {
			ctrl.mutate(base, rng, {
				paramMutationRate: 0.9,
				paramBounds: [0.1, 2.5],
			});
		}

		const summary = ctrl.summary();
		expect(summary.totalAttempts).toBeGreaterThan(0);
		// With high rejection, scale should contract
		expect(ctrl.getParamScale()).toBeLessThan(initialScale);
		expect(summary.currentParamScale).toBe(ctrl.getParamScale());
	});

	it("adaptive controller expands scale when rejection rate is low", () => {
		const base = defaultDesign();
		const ctrl = createAdaptiveMutationController({
			initialParamScale: 0.01,
			expandFactor: 1.2,
			targetRejectionLow: 0.2,
			windowSize: 5,
		});

		const initialScale = ctrl.getParamScale();

		// Mild perturbations that rarely violate kinematic bounds
		const rng = createRng(123);
		for (let i = 0; i < 20; i++) {
			ctrl.mutate(base, rng, {
				paramMutationRate: 0.2,
				paramBounds: [0.95, 1.05],
			});
		}

		expect(ctrl.getParamScale()).toBeGreaterThan(initialScale);
	});

	it("adaptive controller tracks guard violation codes and throttles topology", () => {
		const base = defaultDesign();
		const ctrl = new AdaptiveMutationController({
			initialTopologyRate: 0.3,
			minTopologyRate: 0.01,
			shrinkFactor: 0.7,
			targetRejectionHigh: 0.2,
		});

		// Force recording a failed topology violation
		ctrl.recordStats({
			attemptedOps: 5,
			acceptedOps: 1,
			rejectedOps: 4,
			rejectionRate: 0.8,
			violations: [
				{
					opType: "add_dyad",
					reason: "triangle inequality failed",
					code: "triangle_inequality",
				},
				{
					opType: "set_param",
					param: "jansen_a",
					reason: "cannot assemble",
					code: "cannot_assemble",
				},
			],
		});

		expect(ctrl.getTopologyRate()).toBeLessThan(0.3);
		const summary = ctrl.summary();
		expect(summary.violationsByCode["triangle_inequality"]).toBe(1);
		expect(summary.violationsByCode["cannot_assemble"]).toBe(1);
		expect(summary.violationsByParam["jansen_a"]).toBe(1);
	});

	it("computeDyadEnvelope analyzes distance extrema and sampleDyadLengths satisfies triangle inequality", () => {
		const base = defaultDesign();
		const rng = createRng(777);

		// Ground "G" and crank "C"
		const env = computeDyadEnvelope(base.linkage, "G", "C", 24);
		expect(env).not.toBeNull();
		if (!env) return;

		expect(env.validAngles).toBe(24);
		expect(env.dMin).toBeGreaterThan(0);
		expect(env.dMax).toBeGreaterThanOrEqual(env.dMin);

		const eps = 0.05;
		for (let i = 0; i < 20; i++) {
			const { r1, r2 } = sampleDyadLengths(env.dMin, env.dMax, rng, eps);
			// Triangle inequalities over the entire envelope
			expect(r1 + r2).toBeGreaterThanOrEqual(env.dMax * (1 + eps) - 1e-9);
			expect(Math.abs(r1 - r2)).toBeLessThanOrEqual(
				env.dMin * (1 - eps) + 1e-9,
			);
			expect(r1).toBeGreaterThan(0);
			expect(r2).toBeGreaterThan(0);
		}
	});

	it("adaptive controller decouples topology rejections from continuous parameter scale", () => {
		const ctrl = new AdaptiveMutationController({
			initialParamScale: 0.1,
			initialTopologyRate: 0.3,
			shrinkFactor: 0.7,
			targetRejectionHigh: 0.25,
			windowSize: 10,
		});

		const initialParamScale = ctrl.getParamScale();
		const initialTopologyRate = ctrl.getTopologyRate();

		// Simulate 6 topology mutations that fail (e.g. invalid assembly), but 0 parameter failures
		for (let i = 0; i < 6; i++) {
			ctrl.recordStats({
				attemptedOps: 1,
				acceptedOps: 0,
				rejectedOps: 1,
				rejectionRate: 1.0,
				topoAttempts: 1,
				topoAccepted: 0,
				topoRejected: 1,
				paramAttempts: 0,
				paramAccepted: 0,
				paramRejected: 0,
				violations: [
					{
						opType: "add_dyad",
						reason: "cannot assemble",
						code: "cannot_assemble",
					},
				],
			});
		}

		// Topology rate throttles due to high topology rejection
		expect(ctrl.getTopologyRate()).toBeLessThan(initialTopologyRate);
		// But continuous paramScale must NOT be shrunk by topology failures!
		expect(ctrl.getParamScale()).toBe(initialParamScale);

		// Now simulate parameter mutations that fail
		for (let i = 0; i < 6; i++) {
			ctrl.recordStats({
				attemptedOps: 1,
				acceptedOps: 0,
				rejectedOps: 1,
				rejectionRate: 1.0,
				paramAttempts: 1,
				paramAccepted: 0,
				paramRejected: 1,
				topoAttempts: 0,
				topoAccepted: 0,
				topoRejected: 0,
				violations: [
					{
						opType: "set_param",
						param: "jansen_b",
						reason: "branch flip",
						code: "branch_flip",
					},
				],
			});
		}

		// Now continuous paramScale contracts
		expect(ctrl.getParamScale()).toBeLessThan(initialParamScale);
	});
});
