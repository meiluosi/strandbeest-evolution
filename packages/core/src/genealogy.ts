import type { Design } from "./generated/design";
import { newUlid } from "./ids";
import { diff, type Json } from "./jsonpatch";
import { type Actor, makeOp, type Operation } from "./ops";

export interface GenealogyItem {
	id: string;
	name: string;
	parent?: { id: string } | null;
}

export interface GenealogyNode {
	id: string;
	name: string;
	parentId: string | null;
	depth: number;
	children: GenealogyNode[];
}

export interface ParamDelta {
	name: string;
	before: number | undefined;
	after: number | undefined;
	delta: number | undefined;
}

export interface PropertyDelta {
	path: string;
	before: unknown;
	after: unknown;
}

export interface DesignDiff {
	fromId: string;
	toId: string;
	params: ParamDelta[];
	properties: PropertyDelta[];
	operations: Operation[];
}

/**
 * Fork a design into a child design with a fresh ULID and `parent: { id: parent.id }`.
 */
export function forkDesign(
	parent: Design,
	name = `${parent.name}-fork`,
	id: string = newUlid(),
): Design {
	const copy = JSON.parse(JSON.stringify(parent)) as Design;
	copy.id = id;
	copy.name = name;
	copy.parent = { id: parent.id };
	delete copy.aliases;
	return copy;
}

/**
 * Build a genealogy forest from a list of designs. Nodes whose `parent.id` is not present
 * in `items` (or that would form a cycle) are placed at the root level while keeping `parentId`.
 */
export function buildGenealogyTree(
	items: readonly GenealogyItem[],
): GenealogyNode[] {
	const byId = new Map<string, GenealogyNode>();
	for (const item of items) {
		byId.set(item.id, {
			id: item.id,
			name: item.name,
			parentId: item.parent?.id ?? null,
			depth: 0,
			children: [],
		});
	}

	const roots: GenealogyNode[] = [];
	for (const node of byId.values()) {
		const pid = node.parentId;
		if (!pid || pid === node.id || !byId.has(pid)) {
			roots.push(node);
			continue;
		}
		// Guard against cycles
		let cur: string | null = pid;
		let cycle = false;
		const seen = new Set<string>([node.id]);
		while (cur) {
			if (seen.has(cur)) {
				cycle = true;
				break;
			}
			seen.add(cur);
			cur = byId.get(cur)?.parentId ?? null;
		}
		if (cycle) {
			roots.push(node);
		} else {
			byId.get(pid)?.children.push(node);
		}
	}

	const assignDepth = (nodes: GenealogyNode[], depth: number) => {
		nodes.sort((a, b) => a.id.localeCompare(b.id));
		for (const n of nodes) {
			n.depth = depth;
			assignDepth(n.children, depth + 1);
		}
	};
	assignDepth(roots, 0);
	return roots;
}

/**
 * Pre-order traversal of a genealogy forest for flat rendering with indentation (`node.depth`).
 */
export function flattenGenealogyTree(
	roots: readonly GenealogyNode[],
): GenealogyNode[] {
	const out: GenealogyNode[] = [];
	const visit = (nodes: readonly GenealogyNode[]) => {
		for (const n of nodes) {
			out.push(n);
			visit(n.children);
		}
	};
	visit(roots);
	return out;
}

const COMPARE_PATHS: readonly (readonly string[])[] = [
	["walker", "legs"],
	["walker", "unit_m"],
	["walker", "direction"],
	["walker", "body_mass_kg"],
	["walker", "lateral_spacing_m"],
	["walker", "body_length_m"],
	["drive", "kind"],
	["drive", "motor_omega_rad_s"],
	["manufacturing", "process"],
	["manufacturing", "material"],
	["manufacturing", "bar_width_mm"],
	["manufacturing", "bar_thickness_mm"],
	["manufacturing", "pin_diameter_mm"],
	["manufacturing", "clearance_mm"],
];

function getAtPath(obj: unknown, parts: readonly string[]): unknown {
	let cur: unknown = obj;
	for (const p of parts) {
		if (cur === null || typeof cur !== "object" || !(p in cur))
			return undefined;
		cur = (cur as Record<string, unknown>)[p];
	}
	return cur;
}

/**
 * Compute parameter, property, and operation diffs between any two designs `from` and `to`.
 */
export function diffDesigns(
	from: Design,
	to: Design,
	actor: Actor = { kind: "human", id: "diff" },
	time = "1970-01-01T00:00:00.000Z",
): DesignDiff {
	const params: ParamDelta[] = [];
	const operations: Operation[] = [];
	const allKeys = Array.from(
		new Set([
			...Object.keys(from.linkage.params),
			...Object.keys(to.linkage.params),
		]),
	).sort();

	let opIdx = 0;
	const nextOpId = () => `01DIFFOP${String(++opIdx).padStart(18, "0")}`;

	for (const k of allKeys) {
		const b = from.linkage.params[k];
		const a = to.linkage.params[k];
		if (b !== a) {
			params.push({
				name: k,
				before: b,
				after: a,
				delta: b !== undefined && a !== undefined ? a - b : undefined,
			});
			if (b !== undefined && a !== undefined) {
				operations.push(
					makeOp(
						"set_param",
						{ name: k, value: a },
						{
							id: nextOpId(),
							actor,
							reason: `${b} -> ${a}`,
							time,
						},
					),
				);
			}
		}
	}

	const properties: PropertyDelta[] = [];
	for (const parts of COMPARE_PATHS) {
		const b = getAtPath(from, parts);
		const a = getAtPath(to, parts);
		if (JSON.stringify(b) !== JSON.stringify(a)) {
			const pointer = `/${parts.join("/")}`;
			properties.push({ path: pointer, before: b, after: a });
			if (
				parts[0] === "walker" &&
				parts[1] === "legs" &&
				typeof a === "number"
			) {
				operations.push(
					makeOp(
						"array_legs",
						{ legs: a },
						{
							id: nextOpId(),
							actor,
							reason: `${String(b)} -> ${String(a)}`,
							time,
						},
					),
				);
			} else if (
				parts[0] === "manufacturing" &&
				parts[1] === "material" &&
				(a === "PLA" || a === "PETG")
			) {
				operations.push(
					makeOp(
						"set_material",
						{ material: a },
						{
							id: nextOpId(),
							actor,
							reason: `${String(b)} -> ${String(a)}`,
							time,
						},
					),
				);
			} else if (a !== undefined && b !== undefined) {
				operations.push(
					makeOp(
						"set_property",
						{ path: pointer, value: a },
						{
							id: nextOpId(),
							actor,
							reason: `${String(b)} -> ${String(a)}`,
							time,
						},
					),
				);
			}
		}
	}

	// If topology (joints/foot/crank) changed in ways not covered by param/property ops, include a patch op
	const topoBefore = {
		crank: from.linkage.crank,
		joints: from.linkage.joints,
		foot: from.linkage.foot,
	};
	const topoAfter = {
		crank: to.linkage.crank,
		joints: to.linkage.joints,
		foot: to.linkage.foot,
	};
	if (JSON.stringify(topoBefore) !== JSON.stringify(topoAfter)) {
		const patchSteps = diff(
			{ linkage: topoBefore } as unknown as Json,
			{ linkage: topoAfter } as unknown as Json,
		);
		if (patchSteps.length > 0) {
			properties.push({
				path: "/linkage/joints",
				before: `${from.linkage.joints.length} joints (foot ${from.linkage.foot})`,
				after: `${to.linkage.joints.length} joints (foot ${to.linkage.foot})`,
			});
			operations.push(
				makeOp(
					"patch",
					{ patch: patchSteps },
					{ id: nextOpId(), actor, reason: "linkage topology change", time },
				),
			);
		}
	}

	return {
		fromId: from.id,
		toId: to.id,
		params,
		properties,
		operations,
	};
}
