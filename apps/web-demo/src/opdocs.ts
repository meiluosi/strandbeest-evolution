import opsSchema from "../../../schemas/ops.schema.json";
import { i18n } from "./i18n/index.svelte";

/**
 * Names, descriptions and argument forms of the operations come from schemas/ops.schema.json (x-doc in both languages),
 * so a new operation appears in the command palette and the history with its documentation and no UI code.
 */
type Doc = { zh?: string; en?: string };
export interface FieldSchema {
	type?: string | string[];
	enum?: unknown[];
	const?: unknown;
	default?: unknown;
	minimum?: number;
	exclusiveMinimum?: number;
	minItems?: number;
	items?: FieldSchema;
	$ref?: string;
	oneOf?: FieldSchema[];
	additionalProperties?: FieldSchema | boolean;
	"x-doc"?: Doc;
	"x-unit"?: string;
}
interface ObjSchema {
	properties?: Record<string, FieldSchema>;
	required?: string[];
	"x-doc"?: Doc;
}

const defs = opsSchema.$defs as unknown as Record<
	string,
	ObjSchema & { properties?: Record<string, FieldSchema & { const?: unknown }> }
>;
const pascal = (s: string) =>
	s.replace(/(^|_)(\w)/g, (_, __, c: string) => c.toUpperCase());

/** Operation types that people may apply by hand: every typed operation except the patch used to record an undo. */
export const OP_TYPES: string[] = Object.keys(defs)
	.filter((n) => n.endsWith("Op") && n !== "PatchOp")
	.map((n) => defs[n]?.properties?.type?.const as string);

const doc = (d: Doc | undefined) => (d ? (d[i18n.locale] ?? d.en ?? "") : "");

export function opLabel(type: string): string {
	return doc(defs[`${pascal(type)}Op`]?.["x-doc"]) || type;
}

export function argsDef(type: string): {
	fields: [string, FieldSchema][];
	required: string[];
	title: string;
} {
	const a = defs[`${pascal(type)}Args`];
	return {
		fields: Object.entries(a?.properties ?? {}),
		required: a?.required ?? [],
		title: doc(a?.["x-doc"]),
	};
}

export const fieldDoc = (f: FieldSchema) => doc(f["x-doc"]);
