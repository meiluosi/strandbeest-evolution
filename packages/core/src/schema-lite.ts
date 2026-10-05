/**
 * A small JSON Schema checker for the subset this repo's schemas use (the same subset scripts/gen_models.py supports):
 * type, enum, const, oneOf/anyOf, $ref to #/$defs, minimum/maximum (and exclusive), minLength, pattern, minItems/maxItems,
 * items, properties, required, additionalProperties, minProperties. It lets the browser reject a bad edit exactly as the
 * server (jsonschema) would; contracts/ops/cases.json keeps the two honest. Unknown keywords (x-*, description) are ignored.
 */
import type { Problem } from "./guard";

type Schema = { [k: string]: unknown };

export function schemaProblems(root: Schema, value: unknown): Problem[] {
	const out: Problem[] = [];
	const defs = (root.$defs ?? {}) as Record<string, Schema>;
	const fail = (path: string, message: string): void => {
		out.push({
			level: "error",
			code: "schema",
			path: path || "<root>",
			message: `${path || "<root>"}: ${message}`,
		});
	};

	const kind = (v: unknown): string =>
		v === null
			? "null"
			: Array.isArray(v)
				? "array"
				: typeof v === "number"
					? Number.isInteger(v)
						? "integer"
						: "number"
					: typeof v;
	const typeOk = (t: string, v: unknown) =>
		t === "number" ? typeof v === "number" : kind(v) === t;

	function ok(
		schema: Schema,
		v: unknown,
		path: string,
		collect: Problem[] | null,
	): boolean {
		const before = out.length;
		check(schema, v, path);
		const bad = out.splice(before);
		if (collect) collect.push(...bad);
		return bad.length === 0;
	}

	function check(schema: Schema, v: unknown, path: string): void {
		if (typeof schema.$ref === "string") {
			const target = defs[schema.$ref.split("/").pop() as string];
			if (!target) return fail(path, `unknown reference ${schema.$ref}`);
			return check(target, v, path);
		}
		if ("const" in schema && schema.const !== v)
			return fail(path, `must be ${JSON.stringify(schema.const)}`);
		if (Array.isArray(schema.enum) && !schema.enum.includes(v))
			return fail(
				path,
				`${JSON.stringify(v)} is not one of ${JSON.stringify(schema.enum)}`,
			);
		for (const key of ["oneOf", "anyOf"] as const) {
			const alts = schema[key] as Schema[] | undefined;
			if (alts) {
				const n = alts.filter((a) => ok(a, v, path, null)).length;
				if (key === "oneOf" ? n !== 1 : n === 0)
					fail(
						path,
						`does not match ${key === "oneOf" ? "exactly one" : "any"} of the allowed forms`,
					);
			}
		}
		const types =
			schema.type === undefined
				? null
				: ((Array.isArray(schema.type)
						? schema.type
						: [schema.type]) as string[]);
		if (types && !types.some((t) => typeOk(t, v)))
			return fail(path, `must be ${types.join(" or ")}, got ${kind(v)}`);
		if (typeof v === "number") {
			if (typeof schema.minimum === "number" && v < schema.minimum)
				fail(path, `${v} is less than the minimum of ${schema.minimum}`);
			if (
				typeof schema.exclusiveMinimum === "number" &&
				v <= schema.exclusiveMinimum
			)
				fail(
					path,
					`${v} is less than or equal to the minimum of ${schema.exclusiveMinimum}`,
				);
			if (typeof schema.maximum === "number" && v > schema.maximum)
				fail(path, `${v} is greater than the maximum of ${schema.maximum}`);
			if (
				typeof schema.exclusiveMaximum === "number" &&
				v >= schema.exclusiveMaximum
			)
				fail(
					path,
					`${v} is greater than or equal to the maximum of ${schema.exclusiveMaximum}`,
				);
		}
		if (typeof v === "string") {
			if (typeof schema.minLength === "number" && v.length < schema.minLength)
				fail(path, "is too short");
			if (
				typeof schema.pattern === "string" &&
				!new RegExp(schema.pattern).test(v)
			)
				fail(path, `does not match the pattern ${schema.pattern}`);
		}
		if (Array.isArray(v)) {
			if (typeof schema.minItems === "number" && v.length < schema.minItems)
				fail(path, "has too few items");
			if (typeof schema.maxItems === "number" && v.length > schema.maxItems)
				fail(path, "has too many items");
			if (schema.items)
				v.forEach((x, i) =>
					check(schema.items as Schema, x, path ? `${path}.${i}` : String(i)),
				);
		}
		if (v !== null && typeof v === "object" && !Array.isArray(v)) {
			const obj = v as Record<string, unknown>;
			const props = (schema.properties ?? {}) as Record<string, Schema>;
			for (const r of (schema.required ?? []) as string[])
				if (!(r in obj)) fail(path, `'${r}' is a required property`);
			if (
				typeof schema.minProperties === "number" &&
				Object.keys(obj).length < schema.minProperties
			)
				fail(path, "has too few properties");
			for (const [k, x] of Object.entries(obj)) {
				const sub = path ? `${path}.${k}` : k;
				if (k in props) check(props[k] as Schema, x, sub);
				else if (schema.additionalProperties === false)
					fail(path, `unexpected property '${k}'`);
				else if (
					schema.additionalProperties &&
					typeof schema.additionalProperties === "object"
				)
					check(schema.additionalProperties as Schema, x, sub);
			}
		}
	}

	check(root, value, "");
	return out;
}

/** A guard (see ops.ts) that checks designs against a design schema. */
export function makeSchemaGuard(
	schema: Schema,
): (design: unknown) => Problem[] {
	return (design) => schemaProblems(schema, design);
}
