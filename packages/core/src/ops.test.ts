/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { Design } from "./generated/design";
import { diff, type Json, same } from "./jsonpatch";
import {
	applyOp,
	GuardError,
	History,
	makeGuard,
	makeOp,
	OPS,
	OpError,
	replay,
} from "./ops";
import { createRng } from "./rng";

const root = join(import.meta.dirname, "../../..");
const load = (p: string) => JSON.parse(readFileSync(join(root, p), "utf8"));
const DESIGN = "schemas/examples/design-jansen-small-6leg.json";

type Base = { design: string; linkage?: string | object };
function baseDoc(b: Base): Design {
	const d = load(b.design);
	if (typeof b.linkage === "string") d.linkage = load(b.linkage).spec;
	else if (b.linkage) d.linkage = b.linkage;
	return d;
}
const opOf = (type: string, args: Record<string, unknown>) =>
	makeOp(type as never, args, {
		id: "0000000000YNGRWX0MDFYPZHXT",
		time: "2026-10-06T00:00:00.000Z",
	});
const guard = makeGuard(load("schemas/design.schema.json"));
const errors = (d: Design) => guard(d).filter((p) => p.level === "error");

const cases = load("contracts/ops/cases.json").cases as {
	name: string;
	base: Base;
	ops: { type: string; args: Record<string, unknown> }[];
	expect: {
		patch?: unknown[];
		error?: { kind: string; code?: string; codes?: string[]; step: number };
	};
}[];

describe("operation corpus (shared with Python)", () => {
	for (const c of cases) {
		it(c.name, () => {
			let d = baseDoc(c.base);
			const start = structuredClone(d);
			for (const [i, o] of c.ops.entries()) {
				try {
					d = applyOp(d, opOf(o.type, o.args), [guard]).design;
				} catch (e) {
					if (e instanceof OpError)
						expect(c.expect.error).toEqual({
							kind: "op",
							code: e.code,
							step: i,
						});
					else if (e instanceof GuardError)
						expect(c.expect.error).toEqual({
							kind: "guard",
							codes: e.problems.map((p) => p.code),
							step: i,
						});
					else throw e;
					return;
				}
			}
			expect(
				c.expect.patch,
				"the corpus expected a rejection but every operation was accepted",
			).toBeDefined();
			expect(diff(start as unknown as Json, d as unknown as Json)).toEqual(
				c.expect.patch,
			);
		});
	}
});

describe("add_dyad", () => {
	it("turns the four-bar into exactly the corpus six-bar and passes the guard", () => {
		const four = baseDoc({
			design: DESIGN,
			linkage: "contracts/kinematics/fourbar-crank-rocker.json",
		});
		const six = applyOp(
			four,
			opOf("add_dyad", {
				id: "X",
				centers: ["C", "K"],
				radii: ["p", "q"],
				side: -1,
				params: { p: 30, q: 25 },
				foot: true,
			}),
			[guard],
		).design;
		expect(six.linkage).toEqual(
			load("contracts/kinematics/sixbar-extra-dyad.json").spec,
		);
		expect(errors(six)).toEqual([]);
	});
});

const BASES: Record<string, Design> = {
	jansen: baseDoc({ design: DESIGN }),
	fourbar: baseDoc({
		design: DESIGN,
		linkage: "contracts/kinematics/fourbar-crank-rocker.json",
	}),
	sixbar: baseDoc({
		design: DESIGN,
		linkage: "contracts/kinematics/sixbar-extra-dyad.json",
	}),
};

function randomOp(
	rng: () => number,
	d: Design,
): [string, Record<string, unknown>] {
	const pick = <T>(xs: T[]): T => xs[Math.floor(rng() * xs.length)] as T;
	const lk = d.linkage;
	const points = ["G", "C", ...lk.joints.map((j) => j.id)];
	let kind = pick([
		"set_param",
		"set_param",
		"set_param",
		"set_param",
		"set_param",
		"add_dyad",
		"add_dyad",
		"add_dyad",
		"remove_joint",
		"array_legs",
		"scale",
		"mirror",
		"set_material",
	]);
	if (kind === "remove_joint" && lk.joints.length === 0) kind = "set_param";
	if (kind === "set_param") {
		const names = [...Object.keys(lk.params), "nope"];
		const name = pick(names);
		const cur = lk.params[name] ?? 10;
		return [
			"set_param",
			{
				name,
				value:
					rng() < 0.9
						? cur * pick([0.5, 0.9, 0.99, 1.01, 1.1, 1.5, 3])
						: pick([0, -3, 1e-9]),
			},
		];
	}
	if (kind === "set_length") {
		const keys = [
			"crank.x",
			"crank.length",
			"joint:K.radii.0",
			"joint:J1.radii.1",
			...Object.keys(lk.params),
		];
		return [
			"set_length",
			{ key: pick(keys), value: pick([5, 12, 30, 55, -2]) },
		];
	}
	if (kind === "set_property") {
		return pick<[string, Record<string, unknown>]>([
			[
				"set_property",
				{ path: "/walker/legs", value: pick([0, 2, 6, 12, "six"]) },
			],
			["set_property", { path: "/name", value: pick(["a", "", "walker"]) }],
			[
				"set_property",
				{ path: "/manufacturing/clearance_mm", value: pick([-1, 0.2, 0.4, 3]) },
			],
			[
				"set_property",
				{ path: "/walker/body_mass_kg", value: pick([0, 0.2, 1]) },
			],
			[
				"set_property",
				{ path: "/drive/kind", value: pick(["motor", "sail", "wind"]) },
			],
			["set_property", { path: "/linkage/foot", value: "C" }],
		]);
	}
	if (kind === "add_dyad") {
		const n = Math.floor(rng() * 1000);
		return [
			"add_dyad",
			{
				id: pick([`J${n}`, "K"]),
				centers: [pick(points), pick(points)],
				radii: [`r${n}a`, `r${n}b`],
				side: pick([1, -1]),
				params: { [`r${n}a`]: 10 + 70 * rng(), [`r${n}b`]: 10 + 70 * rng() },
				foot: rng() < 0.5,
			},
		];
	}
	if (kind === "remove_joint")
		return [
			"remove_joint",
			{ id: pick(lk.joints).id, foot: pick(points), drop_params: rng() < 0.7 },
		];
	if (kind === "array_legs")
		return ["array_legs", { legs: pick([0, 1, 4, 6, 12]) }];
	if (kind === "scale")
		return [
			"scale",
			{ factor: pick([0.5, 0.8, 1.25, 2, -1]), keep_physical: rng() < 0.5 },
		];
	if (kind === "mirror") return ["mirror", {}];
	return ["set_material", { material: pick(["PLA", "PETG", "wood"]) }];
}

describe("properties over random operation sequences", () => {
	for (const [name, base] of Object.entries(BASES)) {
		it(`${name}: guard never lets an invalid design through; inverse, replay, undo and redo are exact`, () => {
			expect(errors(base)).toEqual([]);
			const rng = createRng(name.length * 7919);
			let accepted = 0;
			let rejected = 0;
			for (let round = 0; round < 40; round++) {
				const h = new History(base, [guard]);
				const snapshots = [structuredClone(h.design)];
				for (let k = 0; k < 12; k++) {
					const [t, a] = randomOp(rng, h.design);
					const before = structuredClone(h.design);
					let applied: ReturnType<History["commit"]>;
					try {
						applied = h.commit(opOf(t, a));
					} catch (e) {
						if (!(e instanceof OpError || e instanceof GuardError)) throw e;
						rejected++;
						expect(h.design, "a rejected operation changed the design").toEqual(
							before,
						);
						continue;
					}
					accepted++;
					expect(errors(h.design)).toEqual([]);
					expect(
						same(applyOp(h.design, applied.inverse, []).design, before),
					).toBe(true);
					snapshots.push(structuredClone(h.design));
				}
				expect(same(replay(base, h.ops, [guard]), h.design)).toBe(true);
				for (const snap of snapshots.slice(0, -1).reverse()) {
					h.undo();
					expect(same(h.design, snap)).toBe(true);
				}
				expect(h.canUndo).toBe(false);
				expect(same(h.design, base)).toBe(true);
				for (const snap of snapshots.slice(1)) {
					h.redo();
					expect(same(h.design, snap)).toBe(true);
				}
				expect(h.canRedo).toBe(false);
			}
			expect(accepted).toBeGreaterThan(100);
			expect(rejected).toBeGreaterThan(100);
		});
	}

	it("a new commit discards the redo branch", () => {
		const h = new History(BASES.jansen as Design, [guard]);
		h.commit(opOf("array_legs", { legs: 4 }));
		h.undo();
		expect(h.canRedo).toBe(true);
		h.commit(opOf("array_legs", { legs: 8 }));
		expect(h.canRedo).toBe(false);
		expect(h.design.walker.legs).toBe(8);
	});

	it("the guard blames only new errors, so a broken design can be repaired", () => {
		const broken = structuredClone(BASES.jansen as Design);
		broken.linkage.params.h = 1;
		expect(errors(broken).map((p) => p.code)).toEqual(["cannot_assemble"]);
		applyOp(broken, opOf("array_legs", { legs: 4 }), [guard]);
		expect(
			errors(
				applyOp(broken, opOf("set_param", { name: "h", value: 65.7 }), [guard])
					.design,
			),
		).toEqual([]);
	});

	it("patch operations are guarded like any other", () => {
		const d = BASES.jansen as Design;
		expect(() =>
			applyOp(
				d,
				makeOp("patch", {
					patch: [{ op: "replace", path: "/linkage/params/h", value: 1 }],
				}),
			),
		).toThrow(GuardError);
		expect(() =>
			applyOp(d, makeOp("patch", { patch: [{ op: "remove", path: "/nope" }] })),
		).toThrow(/bad_patch/);
	});

	it("operations carry who, why and when", () => {
		const op = makeOp(
			"set_param",
			{ name: "m", value: 14 },
			{ actor: { kind: "agent", id: "claude" }, reason: "longer stride" },
		);
		expect(op.actor).toEqual({ kind: "agent", id: "claude" });
		expect(op.reason).toBe("longer stride");
		expect(op.time.endsWith("Z")).toBe(true);
		const applied = applyOp(BASES.jansen as Design, op, [guard]);
		expect(applied.inverse.type).toBe("patch");
		expect(() =>
			applyOp(BASES.jansen as Design, {
				...op,
				actor: { kind: "ghost", id: "x" } as never,
			}),
		).toThrow(/actor/);
	});

	it("the registry and the schema list the same operation types", () => {
		const schema = load("schemas/ops.schema.json");
		const inSchema = Object.entries(
			schema.$defs as Record<
				string,
				{ properties?: { type?: { const?: string } } }
			>,
		)
			.filter(([n]) => n.endsWith("Op"))
			.map(([, d]) => d.properties?.type?.const)
			.sort();
		expect(inSchema).toEqual([...Object.keys(OPS), "patch"].sort());
	});
});

describe("grouped commits", () => {
	it("a group is one undo step and all or nothing", () => {
		const h = new History(BASES.jansen as Design, [guard]);
		const before = structuredClone(h.design);
		h.commitMany([
			opOf("set_param", { name: "b", value: 42 }),
			opOf("set_param", { name: "d", value: 41 }),
		]);
		expect(h.ops).toHaveLength(2);
		expect(h.steps).toHaveLength(1);
		h.undo();
		expect(h.design).toEqual(before);
		expect(h.ops).toEqual([]);
		h.redo();
		expect(h.ops).toHaveLength(2);
		expect(() =>
			h.commitMany([
				opOf("set_param", { name: "b", value: 40 }),
				opOf("set_param", { name: "h", value: 1 }),
			]),
		).toThrow(GuardError);
		expect(h.design.linkage.params.b).toBe(42);
		expect(h.ops).toHaveLength(2);
		expect(() => h.commitMany([])).toThrow(OpError);
	});
});
