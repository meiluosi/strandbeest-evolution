import { describe, expect, it } from "vitest";
import { defaultDesign } from "./design";
import {
	buildGenealogyTree,
	diffDesigns,
	flattenGenealogyTree,
	forkDesign,
} from "./genealogy";
import { applyOp } from "./ops";

describe("genealogy and design diff (E3-05)", () => {
	it("forkDesign assigns a new id and records parent.id", () => {
		const root = defaultDesign(
			undefined,
			"root-walker",
			"01ARZ3NDEKTSV4RRFFQ69G5FAV",
		);
		root.aliases = ["old-root-name"];
		const child = forkDesign(
			root,
			"child-walker",
			"01ARZ3NDEKTSV4RRFFQ69G5FAW",
		);

		expect(child.id).toBe("01ARZ3NDEKTSV4RRFFQ69G5FAW");
		expect(child.name).toBe("child-walker");
		expect(child.parent).toEqual({ id: root.id });
		expect(child.aliases).toBeUndefined();
		expect(child.linkage.params).toEqual(root.linkage.params);
	});

	it("buildGenealogyTree and flattenGenealogyTree construct depth-ordered hierarchy", () => {
		const root = defaultDesign(undefined, "root", "01ARZ3NDEKTSV4RRFFQ69G5FA1");
		const branchA = forkDesign(root, "branch-a", "01ARZ3NDEKTSV4RRFFQ69G5FA2");
		const branchB = forkDesign(root, "branch-b", "01ARZ3NDEKTSV4RRFFQ69G5FA3");
		const leafA1 = forkDesign(branchA, "leaf-a1", "01ARZ3NDEKTSV4RRFFQ69G5FA4");

		const tree = buildGenealogyTree([leafA1, branchB, root, branchA]);
		expect(tree).toHaveLength(1);
		expect(tree[0]?.id).toBe(root.id);
		expect(tree[0]?.children.map((c) => c.name)).toEqual([
			"branch-a",
			"branch-b",
		]);
		expect(tree[0]?.children[0]?.children[0]?.name).toBe("leaf-a1");

		const flat = flattenGenealogyTree(tree);
		expect(flat.map((n) => [n.name, n.depth])).toEqual([
			["root", 0],
			["branch-a", 1],
			["leaf-a1", 2],
			["branch-b", 1],
		]);
	});

	it("diffDesigns extracts parameter deltas, property changes, and replayable operations", () => {
		const base = defaultDesign(undefined, "base", "01ARZ3NDEKTSV4RRFFQ69G5FA1");
		const child = forkDesign(base, "evolved", "01ARZ3NDEKTSV4RRFFQ69G5FA2");
		child.linkage.params.a = 39.5;
		child.linkage.params.b = 42.0;
		child.walker.legs = 8;
		child.manufacturing.material = "PETG";

		const d = diffDesigns(base, child);
		expect(d.fromId).toBe(base.id);
		expect(d.toId).toBe(child.id);
		expect(d.params).toEqual([
			{ name: "a", before: 38, after: 39.5, delta: 1.5 },
			{ name: "b", before: 41.5, after: 42.0, delta: 0.5 },
		]);
		expect(d.properties).toEqual([
			{ path: "/walker/legs", before: 6, after: 8 },
			{ path: "/manufacturing/material", before: "PLA", after: "PETG" },
		]);
		expect(d.operations.map((o) => o.type)).toEqual([
			"set_param",
			"set_param",
			"array_legs",
			"set_material",
		]);

		// Replaying synthesized operations on `base` yields `child`'s parameters & properties
		let replayed = base;
		for (const op of d.operations) {
			replayed = applyOp(replayed, op).design;
		}
		expect(replayed.linkage.params).toEqual(child.linkage.params);
		expect(replayed.walker.legs).toBe(8);
		expect(replayed.manufacturing.material).toBe("PETG");
	});
});
