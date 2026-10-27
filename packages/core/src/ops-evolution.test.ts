import { describe, expect, it } from "vitest";
import { defaultDesign } from "./design";
import { applyOp, designProblems, replay } from "./ops";
import { mutateDesign } from "./ops-evolution";
import { createRng } from "./rng";

describe("E3-06: operations-driven evolution and mutations", () => {
	it("parameter mutations produce valid set_param operations that replay cleanly", () => {
		const base = defaultDesign();
		const rng = createRng(42);

		const { design: mutated, operations } = mutateDesign(base, rng, {
			paramMutationRate: 0.5,
			paramMutationScale: 0.05,
			topologyMutationRate: 0.0,
		});

		expect(operations.length).toBeGreaterThan(0);
		for (const op of operations) {
			expect(op.type).toBe("set_param");
			expect(op.actor.kind).toBe("algorithm");
		}

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
});
