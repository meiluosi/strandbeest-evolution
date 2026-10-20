/**
 * Schema-driven property metadata extraction (E1-04, ADR-0007).
 *
 * Reads JSON Schema definitions and `x-*` annotations (`x-unit`, `x-range`, `x-group`,
 * `x-doc`, `x-assumption`, `x-source`, `x-calibratable`, `x-affects`) so UI forms render
 * directly from the schema without hand-coding field metadata. Adding a scalar/enum field
 * to a schema section automatically surfaces it in `extractFields`.
 */

export type FieldKind = "number" | "integer" | "string" | "boolean" | "enum";

export interface SchemaField {
	/** Dot-separated path from the document root, e.g. `"name"` or `"walker.legs"`. */
	path: string;
	/** JSON Pointer path, e.g. `"/name"` or `"/walker/legs"`. */
	pointer: string;
	/** Leaf property name, e.g. `"legs"`. */
	key: string;
	/** Top-level section name (`""` for root properties, `"walker"`, `"run"`, `"solver"`, etc.). */
	section: string;
	kind: FieldKind;
	enumValues?: Array<string | number>;
	/** Display unit (omits dimensionless `"1"` and `"count"`). */
	unit: string;
	/** Raw `x-unit` annotation from the schema. */
	rawUnit?: string;
	range?: [number, number];
	min?: number;
	max?: number;
	step?: number;
	defaultValue?: unknown;
	group?: string;
	doc: { zh: string; en: string };
	assumption: boolean;
	source?: string;
	calibratable: boolean;
	affects: string[];
	nullable: boolean;
}

export interface ExtractOptions {
	/**
	 * Top-level sections to include (`""` for root scalar fields, `"walker"`, `"run"`, `"solver"`, etc.).
	 * Any new scalar/enum field added to an included section in the schema is extracted automatically.
	 */
	sections?: string[];
	/** Optional explicit allowlist of dot paths; if omitted, all scalar/enum fields in `sections` are returned. */
	include?: string[];
	/** Optional denylist of dot paths to skip. */
	exclude?: string[];
	/** Optional filter by `x-group` values. */
	groups?: string[];
}

const INTERNAL_ROOT_KEYS = new Set([
	"$schema",
	"$id",
	"schema_version",
	"id",
	"parent",
	"aliases",
	"linkage",
	"entities",
]);

type RawNode = Record<string, unknown>;

function resolveNode(node: RawNode, defs: Record<string, RawNode>): RawNode {
	if (typeof node.$ref === "string" && node.$ref.startsWith("#/$defs/")) {
		const defName = node.$ref.slice("#/$defs/".length);
		const target = defs[defName];
		if (target) {
			const merged: RawNode = { ...resolveNode(target, defs), ...node };
			delete merged.$ref;
			return merged;
		}
	}
	return node;
}

function inferStep(
	kind: FieldKind,
	range?: [number, number],
	defaultValue?: unknown,
	min?: number,
): number | undefined {
	if (kind === "integer") return 1;
	if (kind !== "number") return undefined;
	if (typeof defaultValue === "number" && defaultValue !== 0) {
		const abs = Math.abs(defaultValue);
		if (abs < 0.001) return 0.0001;
		if (abs < 0.01) return 0.0005;
		if (abs < 0.1) return 0.005;
		if (abs < 1) return 0.05;
		if (abs >= 1000) return 1000;
	}
	if (range) {
		const span = range[1] - range[0];
		if (span <= 0.01) return 0.0005;
		if (span <= 0.1) return 0.005;
		if (span <= 5) return 0.1;
		if (span >= 10000) return 1000;
	}
	if (typeof min === "number" && min > 0 && min < 0.01) return 0.001;
	return 0.1;
}

function toLeafField(
	path: string,
	section: string,
	raw: RawNode,
	defs: Record<string, RawNode>,
	inheritedGroup?: string,
): SchemaField | null {
	const node = resolveNode(raw, defs);
	if ("const" in node) return null;

	let nullable = false;
	let rawType = node.type;
	if (Array.isArray(rawType)) {
		nullable = rawType.includes("null");
		const nonNull = rawType.filter((t) => t !== "null");
		if (nonNull.length !== 1) return null;
		rawType = nonNull[0];
	}

	let kind: FieldKind | null = null;
	let enumValues: Array<string | number> | undefined;
	if (Array.isArray(node.enum)) {
		kind = "enum";
		enumValues = node.enum.filter(
			(v): v is string | number =>
				typeof v === "string" || typeof v === "number",
		);
	} else if (rawType === "number") {
		kind = "number";
	} else if (rawType === "integer") {
		kind = "integer";
	} else if (rawType === "string") {
		kind = "string";
	} else if (rawType === "boolean") {
		kind = "boolean";
	}
	if (!kind) return null;

	const rawUnit =
		typeof node["x-unit"] === "string" ? node["x-unit"] : undefined;
	const unit = rawUnit && rawUnit !== "1" && rawUnit !== "count" ? rawUnit : "";
	const range =
		Array.isArray(node["x-range"]) &&
		node["x-range"].length === 2 &&
		typeof node["x-range"][0] === "number" &&
		typeof node["x-range"][1] === "number"
			? ([node["x-range"][0], node["x-range"][1]] as [number, number])
			: undefined;

	const min =
		typeof node.minimum === "number"
			? node.minimum
			: typeof node.exclusiveMinimum === "number"
				? node.exclusiveMinimum
				: range?.[0];
	const max =
		typeof node.maximum === "number"
			? node.maximum
			: typeof node.exclusiveMaximum === "number"
				? node.exclusiveMaximum
				: range?.[1];

	const xdoc = (node["x-doc"] ?? {}) as Record<string, unknown>;
	const key = path.split(".").at(-1) ?? path;
	const doc = {
		zh: typeof xdoc.zh === "string" ? xdoc.zh : key,
		en: typeof xdoc.en === "string" ? xdoc.en : key,
	};
	const group =
		typeof node["x-group"] === "string" ? node["x-group"] : inheritedGroup;
	const assumption = node["x-assumption"] === true;
	const source =
		typeof node["x-source"] === "string" ? node["x-source"] : undefined;
	const calibratable = node["x-calibratable"] === true;
	const affects = Array.isArray(node["x-affects"])
		? node["x-affects"].filter((x): x is string => typeof x === "string")
		: [];

	return {
		path,
		pointer: `/${path.split(".").join("/")}`,
		key,
		section,
		kind,
		enumValues,
		unit,
		rawUnit,
		range,
		min,
		max,
		step: inferStep(kind, range, node.default, min),
		defaultValue: node.default,
		group,
		doc,
		assumption,
		source,
		calibratable,
		affects,
		nullable,
	};
}

export function extractFields(
	schema: Record<string, unknown>,
	options: ExtractOptions = {},
): SchemaField[] {
	const defs = (schema.$defs ?? {}) as Record<string, RawNode>;
	const props = (schema.properties ?? {}) as Record<string, RawNode>;
	const sections = options.sections ? new Set(options.sections) : null;
	const include = options.include ? new Set(options.include) : null;
	const exclude = options.exclude
		? new Set(options.exclude)
		: new Set<string>();
	const groups = options.groups ? new Set(options.groups) : null;

	const out: SchemaField[] = [];

	function walkObject(
		objProps: Record<string, RawNode>,
		prefix: string,
		section: string,
		inheritedGroup?: string,
	) {
		for (const [k, rawProp] of Object.entries(objProps)) {
			if (!prefix && INTERNAL_ROOT_KEYS.has(k)) continue;
			const path = prefix ? `${prefix}.${k}` : k;
			const topSection =
				section || (prefix ? (prefix.split(".")[0] ?? "") : "");
			const resolved = resolveNode(rawProp, defs);
			const group =
				typeof resolved["x-group"] === "string"
					? resolved["x-group"]
					: inheritedGroup;

			if (
				resolved.type === "object" &&
				resolved.properties &&
				typeof resolved.properties === "object"
			) {
				const nextSection = prefix ? topSection : k;
				if (!sections || sections.has(nextSection)) {
					walkObject(
						resolved.properties as Record<string, RawNode>,
						path,
						nextSection,
						group,
					);
				}
				continue;
			}

			const currentSection = prefix ? topSection : "";
			if (sections && !sections.has(currentSection)) continue;
			if (exclude.has(path)) continue;
			if (include && !include.has(path)) continue;

			const field = toLeafField(path, currentSection, resolved, defs, group);
			if (!field) continue;
			if (groups && (!field.group || !groups.has(field.group))) continue;
			out.push(field);
		}
	}

	walkObject(props, "", "");
	return out;
}

export function getByPath(obj: unknown, path: string): unknown {
	let cur: unknown = obj;
	for (const part of path.split(".")) {
		if (!part) continue;
		if (cur === null || typeof cur !== "object") return undefined;
		cur = (cur as Record<string, unknown>)[part];
	}
	return cur;
}

export function setByPath<T extends Record<string, unknown>>(
	obj: T,
	path: string,
	value: unknown,
): T {
	const clone = JSON.parse(JSON.stringify(obj)) as T;
	const parts = path.split(".").filter(Boolean);
	let cur: Record<string, unknown> = clone;
	for (const part of parts.slice(0, -1)) {
		if (cur[part] === null || typeof cur[part] !== "object") {
			cur[part] = {};
		}
		cur = cur[part] as Record<string, unknown>;
	}
	const last = parts.at(-1);
	if (last) cur[last] = value;
	return clone;
}
