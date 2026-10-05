/**
 * A small deterministic JSON diff/patch (RFC 6901 pointers; add/replace/remove on objects, replace on arrays).
 * Makes every edit exactly reversible: the inverse of an operation is the patch that turns the new design back into the
 * old one. Twin of strandbeest_common/jsonpatch.py; both are checked against contracts/ops/cases.json.
 * Arrays of equal length are compared element by element, any other change to an array replaces it whole.
 */
export type Json =
	| null
	| boolean
	| number
	| string
	| Json[]
	| { [k: string]: Json };
export interface PatchStep {
	op: "add" | "replace" | "remove";
	path: string;
	value?: Json;
}

const isObj = (v: unknown): v is { [k: string]: Json } =>
	typeof v === "object" && v !== null && !Array.isArray(v);

export function same(a: unknown, b: unknown): boolean {
	if (isObj(a) && isObj(b)) {
		const ka = Object.keys(a);
		return (
			ka.length === Object.keys(b).length &&
			ka.every((k) => k in b && same(a[k], b[k]))
		);
	}
	if (Array.isArray(a) && Array.isArray(b))
		return a.length === b.length && a.every((x, i) => same(x, b[i]));
	return a === b;
}

export const pointer = (...parts: (string | number)[]): string =>
	parts
		.map((p) => `/${String(p).replace(/~/g, "~0").replace(/\//g, "~1")}`)
		.join("");

const split = (path: string): string[] => {
	if (path === "") return [];
	if (!path.startsWith("/")) throw new Error(`bad JSON pointer: ${path}`);
	return path
		.slice(1)
		.split("/")
		.map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
};

const clone = <T>(v: T): T =>
	v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T);

const sortedKeys = (a: object, b: object): string[] =>
	[...new Set([...Object.keys(a), ...Object.keys(b)])].sort((x, y) =>
		x < y ? -1 : x > y ? 1 : 0,
	);

export function diff(
	a: Json,
	b: Json,
	path: (string | number)[] = [],
): PatchStep[] {
	if (same(a, b)) return [];
	if (isObj(a) && isObj(b)) {
		const steps: PatchStep[] = [];
		for (const k of sortedKeys(a, b)) {
			if (!(k in b)) steps.push({ op: "remove", path: pointer(...path, k) });
			else if (!(k in a))
				steps.push({
					op: "add",
					path: pointer(...path, k),
					value: clone(b[k] as Json),
				});
			else steps.push(...diff(a[k] as Json, b[k] as Json, [...path, k]));
		}
		return steps;
	}
	if (Array.isArray(a) && Array.isArray(b) && a.length === b.length) {
		const steps: PatchStep[] = [];
		a.forEach((x, i) => {
			steps.push(...diff(x, b[i] as Json, [...path, i]));
		});
		return steps;
	}
	return [{ op: "replace", path: pointer(...path), value: clone(b) }];
}

function index(arr: Json[], key: string, path: string): number {
	if (!/^\d+$/.test(key) || Number(key) >= arr.length)
		throw new Error(`bad array index in ${path}`);
	return Number(key);
}

function child(parent: Json, key: string, path: string): Json {
	if (Array.isArray(parent)) return parent[index(parent, key, path)] as Json;
	if (isObj(parent) && key in parent) return parent[key] as Json;
	throw new Error(`path does not exist: ${path}`);
}

/** A patched deep copy of `doc`; throws when a step does not fit the document. */
export function applyPatch<T extends Json>(doc: T, steps: PatchStep[]): T {
	let out: Json = clone(doc);
	for (const s of steps) {
		const keys = split(s.path);
		if (keys.length === 0) {
			if (s.op !== "replace") throw new Error("the root can only be replaced");
			out = clone(s.value as Json);
			continue;
		}
		let parent: Json = out;
		for (const k of keys.slice(0, -1)) parent = child(parent, k, s.path);
		const last = keys[keys.length - 1] as string;
		if (Array.isArray(parent)) {
			if (s.op !== "replace")
				throw new Error(`only replace is supported inside arrays: ${s.path}`);
			parent[index(parent, last, s.path)] = clone(s.value as Json);
		} else if (isObj(parent)) {
			if (s.op === "remove") {
				if (!(last in parent))
					throw new Error(`nothing to remove at ${s.path}`);
				delete parent[last];
			} else if (s.op === "replace") {
				if (!(last in parent))
					throw new Error(`nothing to replace at ${s.path}`);
				parent[last] = clone(s.value as Json);
			} else if (s.op === "add") parent[last] = clone(s.value as Json);
			else throw new Error(`unknown patch op ${String(s.op)}`);
		} else throw new Error(`cannot step into a scalar at ${s.path}`);
	}
	return out as T;
}
