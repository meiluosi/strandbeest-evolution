import type { Design } from "./generated/design";
import type { OpLogActor, OpLogOperation } from "./generated/ops";
import { kinematicProblems, type Problem } from "./guard";
import { newUlid } from "./ids";
import { applyPatch, diff, type Json, type PatchStep } from "./jsonpatch";
import { schemaProblems } from "./schema-lite";

/**
 * The edit algebra (ADR-0003, E3-02/E3-03): every change to a design is a typed, reversible, logged operation.
 * Twin of strandbeest_common/ops.py; both are checked against contracts/ops/cases.json. See ops.py for the full story.
 */
export type Operation = OpLogOperation;
export type Actor = OpLogActor;
export type { Problem };
export type Guard = (design: Design) => Problem[];

export class OpError extends Error {
	constructor(
		readonly code: string,
		readonly detail: string,
	) {
		super(`${code}: ${detail}`);
	}
}

export class GuardError extends Error {
	constructor(readonly problems: Problem[]) {
		super(
			`rejected by the validity guard: ${problems.map((p) => `${p.code} (${p.message})`).join("; ")}`,
		);
	}
}

export const ACTOR_KINDS = ["human", "algorithm", "agent"] as const;
export const designProblems: Guard = (d) => kinematicProblems(d.linkage);

/** Schema first, then kinematics (the kinematic checks assume a well-formed linkage). Twin of guard.default_problems. */
export function makeGuard(designSchema: { [k: string]: unknown }): Guard {
	return (d) => {
		const bad = schemaProblems(designSchema, d);
		return bad.length ? bad : designProblems(d);
	};
}

export function makeOp(
	type: Operation["type"],
	args: Record<string, unknown>,
	opts: { actor?: Actor; reason?: string; time?: string; id?: string } = {},
): Operation {
	return {
		id: opts.id ?? newUlid(),
		type,
		args,
		actor: opts.actor ?? { kind: "human", id: "unknown" },
		reason: opts.reason ?? "",
		time: opts.time ?? new Date().toISOString(),
	} as Operation;
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const isNum = (v: unknown): v is number =>
	typeof v === "number" && Number.isFinite(v);

function need<T>(
	args: Record<string, unknown>,
	key: string,
	ok: (v: unknown) => v is T,
	what: string,
): T {
	const v = args[key];
	if (!ok(v)) throw new OpError("bad_args", `'${key}' must be ${what}`);
	return v;
}
const isStr = (v: unknown): v is string => typeof v === "string";

/** Where every named param is used: name -> places. */
function refs(doc: Design): Map<string, string[]> {
	const uses = new Map<string, string[]>();
	const add = (name: string, where: string) =>
		uses.set(name, [...(uses.get(name) ?? []), where]);
	const lk = doc.linkage;
	for (const key of ["x", "y", "length"] as const) {
		const r = lk.crank[key];
		if (typeof r === "string") add(r, `crank.${key}`);
	}
	for (const j of lk.joints)
		j.radii.forEach((r, k) => {
			if (typeof r === "string") add(r, `${j.id}.radii[${k}]`);
		});
	return uses;
}

type Handler = (doc: Design, args: Record<string, unknown>) => void;

const setParam: Handler = (doc, a) => {
	const name = need(a, "name", isStr, "a string");
	const value = need(a, "value", isNum, "a number");
	const params = doc.linkage.params;
	if (!(name in params))
		throw new OpError("unknown_param", `'${name}' is not an entry of params`);
	params[name] = value;
};

const addDyad: Handler = (doc, a) => {
	const lk = doc.linkage;
	const id = need(a, "id", isStr, "a string");
	const centers = a.centers;
	const radii = a.radii;
	if (!Array.isArray(centers) || !Array.isArray(radii))
		throw new OpError("bad_args", "'centers' and 'radii' must be lists");
	const side = a.side;
	if (side !== 1 && side !== -1)
		throw new OpError("bad_args", "'side' must be 1 or -1");
	if (centers.length !== 2 || radii.length !== 2)
		throw new OpError(
			"bad_args",
			"'centers' and 'radii' need exactly two entries",
		);
	const newParams = (a.params ?? {}) as Record<string, unknown>;
	if (
		typeof newParams !== "object" ||
		Array.isArray(newParams) ||
		newParams === null
	)
		throw new OpError(
			"bad_args",
			"'params' must be an object of new named lengths",
		);
	for (const [name, v] of Object.entries(newParams)) {
		if (name in lk.params)
			throw new OpError(
				"param_exists",
				`'${name}' already exists; use set_param to change it`,
			);
		if (!isNum(v))
			throw new OpError("bad_args", `params.${name} must be a number`);
	}
	if (lk.joints.some((j) => j.id === id))
		throw new OpError("joint_exists", `a joint '${id}' already exists`);
	Object.assign(lk.params, newParams);
	lk.joints.push({
		id,
		centers: [...centers] as [string, string],
		radii: [...radii] as [string | number, string | number],
		side,
	});
	if (a.foot) lk.foot = id;
};

const removeJoint: Handler = (doc, a) => {
	const lk = doc.linkage;
	const id = need(a, "id", isStr, "a string");
	const victim = lk.joints.find((j) => j.id === id);
	if (!victim) throw new OpError("unknown_joint", `no joint '${id}'`);
	const users = lk.joints
		.filter((j) => j.centers.includes(id))
		.map((j) => j.id);
	if (users.length)
		throw new OpError(
			"joint_in_use",
			`joint(s) ${users.join(", ")} are built on '${id}'; remove those first`,
		);
	if (lk.foot === id) {
		const newFoot = a.foot;
		if (!isStr(newFoot))
			throw new OpError(
				"foot_needed",
				`'${id}' is the foot; give the id of the new foot in 'foot'`,
			);
		if (
			newFoot === id ||
			(newFoot !== "C" && !lk.joints.some((j) => j.id === newFoot))
		)
			throw new OpError(
				"unknown_joint",
				`the new foot '${newFoot}' is not a remaining joint`,
			);
		lk.foot = newFoot;
	}
	const before = refs(doc);
	lk.joints = lk.joints.filter((j) => j.id !== id);
	if (a.drop_params ?? true) {
		const still = refs(doc);
		for (const r of victim.radii)
			if (typeof r === "string" && before.has(r) && !still.has(r))
				delete lk.params[r];
	}
};

function handleTarget(
	doc: Design,
	key: string,
): { holder: Record<string | number, unknown>; at: string | number } {
	const lk = doc.linkage;
	if (key in lk.params) return { holder: lk.params, at: key };
	if (key === "crank.x" || key === "crank.y" || key === "crank.length") {
		const name = key.split(".")[1] as "x" | "y" | "length";
		if (typeof lk.crank[name] === "string")
			throw new OpError(
				"not_inline",
				`'${key}' is the named length '${lk.crank[name]}'; set that param instead`,
			);
		return { holder: lk.crank as unknown as Record<string, unknown>, at: name };
	}
	const m = /^joint:(.+)\.radii\.([01])$/.exec(key);
	const joint = m && lk.joints.find((j) => j.id === m[1]);
	if (m && joint) {
		const k = Number(m[2]);
		if (typeof joint.radii[k] === "string")
			throw new OpError(
				"not_inline",
				`'${key}' is the named length '${joint.radii[k]}'; set that param instead`,
			);
		return { holder: joint.radii as unknown as Record<number, unknown>, at: k };
	}
	throw new OpError(
		"unknown_length",
		`'${key}' is not a length of this linkage`,
	);
}

const setLength: Handler = (doc, a) => {
	const key = need(a, "key", isStr, "a string");
	const value = need(a, "value", isNum, "a number");
	const { holder, at } = handleTarget(doc, key);
	holder[at] = value;
};

const EDITABLE_ROOTS = ["name", "notes", "walker", "drive", "manufacturing"];
const kindOf = (v: unknown) =>
	v === null
		? "null"
		: Array.isArray(v)
			? "array"
			: typeof v === "object"
				? "object"
				: typeof v;

const setProperty: Handler = (doc, a) => {
	const path = need(a, "path", isStr, "a JSON pointer such as /walker/legs");
	const parts = path.startsWith("/")
		? path
				.slice(1)
				.split("/")
				.map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"))
		: null;
	if (!parts || !EDITABLE_ROOTS.includes(parts[0] as string))
		throw new OpError(
			"not_editable",
			`'${path}' is not an editable property (editable: ${EDITABLE_ROOTS.map((r) => `/${r}`).join(", ")})`,
		);
	if (!("value" in a)) throw new OpError("bad_args", "'value' is required");
	let node: unknown = doc;
	for (const p of parts.slice(0, -1)) {
		if (
			node !== null &&
			typeof node === "object" &&
			!Array.isArray(node) &&
			p in (node as object)
		)
			node = (node as Record<string, unknown>)[p];
		else
			throw new OpError(
				"unknown_property",
				`'${path}' does not exist in this design`,
			);
	}
	const last = parts[parts.length - 1] as string;
	if (
		node === null ||
		typeof node !== "object" ||
		Array.isArray(node) ||
		!(last in (node as object))
	)
		throw new OpError(
			"unknown_property",
			`'${path}' does not exist in this design`,
		);
	const holder = node as Record<string, unknown>;
	if (kindOf(holder[last]) !== kindOf(a.value))
		throw new OpError(
			"bad_args",
			`'${path}' holds a ${kindOf(holder[last])}; the value is a ${kindOf(a.value)}`,
		);
	holder[last] = a.value;
};

const arrayLegs: Handler = (doc, a) => {
	const n = need(
		a,
		"legs",
		(v): v is number => Number.isInteger(v),
		"an integer",
	);
	if (n < 1) throw new OpError("bad_args", "'legs' must be at least 1");
	doc.walker.legs = n;
};

const scale: Handler = (doc, a) => {
	const f = need(a, "factor", isNum, "a number");
	if (f <= 0) throw new OpError("bad_args", "'factor' must be positive");
	const lk = doc.linkage;
	for (const k of Object.keys(lk.params))
		lk.params[k] = (lk.params[k] as number) * f;
	for (const key of ["x", "y", "length"] as const) {
		const r = lk.crank[key];
		if (typeof r !== "string") lk.crank[key] = r * f;
	}
	for (const j of lk.joints)
		j.radii = j.radii.map((r) => (typeof r === "string" ? r : r * f)) as [
			string | number,
			string | number,
		];
	if (a.keep_physical) doc.walker.unit_m = doc.walker.unit_m / f;
};

const mirror: Handler = (doc) => {
	const lk = doc.linkage;
	const r = lk.crank.x;
	if (typeof r === "string") {
		if ((refs(doc).get(r) ?? []).length !== 1)
			throw new OpError(
				"shared_param",
				`crank.x uses '${r}', which is shared with other places; give the crank pivot its own length first`,
			);
		lk.params[r] = -(lk.params[r] as number);
	} else lk.crank.x = -r;
	for (const j of lk.joints) j.side = -j.side as 1 | -1;
	doc.walker.direction = -doc.walker.direction as 1 | -1;
};

const setMaterial: Handler = (doc, a) => {
	const m = need(a, "material", isStr, "a string");
	if (m !== "PLA" && m !== "PETG")
		throw new OpError("bad_args", "'material' must be PLA or PETG");
	doc.manufacturing.material = m;
};

export const OPS: Record<string, { apply: Handler; doc: string }> = {
	set_param: { apply: setParam, doc: "Set one named length of the linkage." },
	add_dyad: {
		apply: addDyad,
		doc: "Add a joint at the intersection of two circles (optionally with new named lengths, optionally as the foot).",
	},
	remove_joint: {
		apply: removeJoint,
		doc: "Remove a joint nothing else is built on (naming a new foot if it was the foot).",
	},
	set_length: {
		apply: setLength,
		doc: "Set one length by handle: a named param, an inline crank length, or an inline bar length.",
	},
	set_property: {
		apply: setProperty,
		doc: "Set an existing editable property of the design (name, notes, walker, drive, manufacturing).",
	},
	array_legs: {
		apply: arrayLegs,
		doc: "Set the number of legs around the axle.",
	},
	scale: {
		apply: scale,
		doc: "Multiply every length of the linkage by a factor (optionally keeping the physical size by changing the unit).",
	},
	mirror: {
		apply: mirror,
		doc: "Reflect the leg left to right and reverse the crank direction.",
	},
	set_material: { apply: setMaterial, doc: "Choose the printing material." },
};

export interface Applied {
	design: Design;
	inverse: Operation;
	warnings: Problem[];
}

const key = (p: Problem) => `${p.code}\u0000${p.path}`;

function checkEnvelope(op: Operation) {
	for (const k of ["id", "type", "args", "actor", "reason", "time"])
		if (!(k in op)) throw new OpError("bad_op", `operation is missing '${k}'`);
	if (!ACTOR_KINDS.includes(op.actor?.kind) || typeof op.actor?.id !== "string")
		throw new OpError(
			"bad_op",
			"actor must be {kind: human|algorithm|agent, id}",
		);
}

/**
 * Apply `op` to a copy of `design`. Throws OpError (cannot apply) or GuardError (would introduce errors); the input is
 * never changed. Errors that were already there before the operation do not block it (so a broken design can be
 * repaired step by step); any error that is new does.
 */
export function applyOp(
	design: Design,
	op: Operation,
	guards: Guard[] = [designProblems],
): Applied {
	checkEnvelope(op);
	let next: Design = clone(design);
	if (op.type === "patch") {
		try {
			next = applyPatch(
				next as unknown as Json,
				(op.args as { patch: PatchStep[] }).patch,
			) as unknown as Design;
		} catch (e) {
			throw new OpError("bad_patch", (e as Error).message);
		}
	} else {
		const t = OPS[op.type];
		if (!t)
			throw new OpError(
				"unknown_type",
				`unknown operation type '${op.type}'; known: ${Object.keys(OPS).sort().join(", ")}, patch`,
			);
		t.apply(next, op.args as Record<string, unknown>);
	}
	const before = guards.flatMap((g) => g(design));
	const after = guards.flatMap((g) => g(next));
	const known = new Set(before.filter((p) => p.level === "error").map(key));
	const fresh = after.filter((p) => p.level === "error" && !known.has(key(p)));
	if (fresh.length) throw new GuardError(fresh);
	const inverse = makeOp(
		"patch",
		{ patch: diff(next as unknown as Json, design as unknown as Json) },
		{
			actor: op.actor,
			reason: `undo ${op.type} ${op.id}`,
		},
	);
	return {
		design: next,
		inverse,
		warnings: after.filter((p) => p.level === "warning"),
	};
}

export function replay(
	base: Design,
	ops: Operation[],
	guards: Guard[] = [designProblems],
): Design {
	return ops.reduce((d, op) => applyOp(d, op, guards).design, base);
}

interface Entry {
	ops: Operation[];
	forward: PatchStep[];
	backward: PatchStep[];
}

/** A design with its log, undo and redo. The log (`ops`) is the source of truth; `design` is its fold. */
export class History {
	readonly base: Design;
	design: Design;
	private done: Entry[] = [];
	private undone: Entry[] = [];

	constructor(
		base: Design,
		private readonly guards: Guard[] = [designProblems],
	) {
		this.base = clone(base);
		this.design = clone(base);
	}

	get ops(): Operation[] {
		return this.done.flatMap((e) => e.ops);
	}
	/** Undo steps, oldest first (a step may hold several operations). */
	get steps(): Operation[][] {
		return this.done.map((e) => e.ops);
	}
	get canUndo(): boolean {
		return this.done.length > 0;
	}
	get canRedo(): boolean {
		return this.undone.length > 0;
	}

	commit(op: Operation): Applied {
		return this.commitMany([op]).at(-1) as Applied;
	}

	/** Apply several operations as ONE undo step (e.g. dragging a point changes two bar lengths). All or nothing. */
	commitMany(ops: Operation[]): Applied[] {
		if (!ops.length) throw new OpError("bad_op", "nothing to commit");
		let design = this.design;
		const applied: Applied[] = [];
		for (const op of ops) {
			const a = applyOp(design, op, this.guards);
			applied.push(a);
			design = a.design;
		}
		this.done.push({
			ops: [...ops],
			forward: diff(this.design as unknown as Json, design as unknown as Json),
			backward: diff(design as unknown as Json, this.design as unknown as Json),
		});
		this.undone = [];
		this.design = design;
		return applied;
	}

	/** Undo the last step (restoring a previous state is always allowed); returns the operations undone. */
	undo(): Operation[] {
		const e = this.done.pop();
		if (!e) throw new OpError("nothing_to_undo", "the log is empty");
		this.design = applyPatch(
			this.design as unknown as Json,
			e.backward,
		) as unknown as Design;
		this.undone.push(e);
		return e.ops;
	}

	redo(): Operation[] {
		const e = this.undone.pop();
		if (!e) throw new OpError("nothing_to_redo", "there is nothing to redo");
		this.design = applyPatch(
			this.design as unknown as Json,
			e.forward,
		) as unknown as Design;
		this.done.push(e);
		return e.ops;
	}
}
