import type { LinkageSpec } from "./linkage";

/**
 * Static validity of a linkage spec (E3-01, extended by the validity guard of E3-02). Twin of
 * strandbeest_common/validity.py, both checked against contracts/linkage-structure/cases.json.
 * The JSON Schema fixes the shape; these rules say that names refer to something, that a joint only uses points
 * solved before it, and that bars have positive length.
 */
export interface StructureError {
	code: string;
	path: string;
	message: string;
}

const RESERVED = new Set(["G", "C", "P"]);

export function structureErrors(spec: LinkageSpec): StructureError[] {
	const errs: StructureError[] = [];
	const err = (code: string, path: string, message: string) =>
		errs.push({ code, path, message });
	const params = spec.params ?? {};
	const value = (ref: unknown, path: string): number | null => {
		if (typeof ref === "number") return ref;
		if (typeof ref === "string") {
			if (ref in params) return params[ref] as number;
			err("unknown_param", path, `${path}: '${ref}' is not an entry of params`);
		}
		return null;
	};
	value(spec.crank?.x, "crank.x");
	value(spec.crank?.y, "crank.y");
	const length = value(spec.crank?.length, "crank.length");
	if (length !== null && length <= 0)
		err(
			"non_positive_length",
			"crank.length",
			`crank.length: the crank must have positive length, got ${length}`,
		);

	const solved = ["G", "C"];
	const ids = (spec.joints ?? []).map((j) => j.id);
	const seen = new Set<string>();
	(spec.joints ?? []).forEach((j, i) => {
		const base = `joints[${i}]`;
		if (RESERVED.has(j.id))
			err(
				"reserved_id",
				`${base}.id`,
				`${base}.id: '${j.id}' is reserved (G ground, C crank tip, P crank pivot)`,
			);
		else if (seen.has(j.id))
			err(
				"duplicate_id",
				`${base}.id`,
				`${base}.id: '${j.id}' is defined twice`,
			);
		seen.add(j.id);
		j.centers.forEach((c, k) => {
			if (solved.includes(c)) return;
			if (ids.slice(i + 1).includes(c))
				err(
					"forward_reference",
					`${base}.centers[${k}]`,
					`${base}.centers[${k}]: '${c}' is solved after '${j.id}'; order joints so each uses earlier points`,
				);
			else
				err(
					"unknown_point",
					`${base}.centers[${k}]`,
					`${base}.centers[${k}]: '${c}' is not a point of this linkage`,
				);
		});
		if (j.centers.length === 2 && j.centers[0] === j.centers[1])
			err(
				"degenerate_centers",
				`${base}.centers`,
				`${base}.centers: both circles are centred on '${j.centers[0]}'`,
			);
		j.radii.forEach((r, k) => {
			const v = value(r, `${base}.radii[${k}]`);
			if (v !== null && v <= 0)
				err(
					"non_positive_length",
					`${base}.radii[${k}]`,
					`${base}.radii[${k}]: a bar must have positive length, got ${v}`,
				);
		});
		solved.push(j.id);
	});
	if (!solved.includes(spec.foot) || spec.foot === "G")
		err(
			"unknown_foot",
			"foot",
			`foot: '${spec.foot}' is not a joint of this linkage`,
		);
	return errs;
}
