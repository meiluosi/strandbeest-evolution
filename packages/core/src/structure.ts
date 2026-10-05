import type { LinkageSpec, ParamRef } from "./linkage";

/**
 * Everything a viewer, an editor or an optimiser needs to know about a linkage is derived from its LinkageSpec,
 * so any chain of dyads works, not just Jansen's. (E3-01)
 */

/** Ids of the fixed pivots: "G" is the origin (hip), "P" the crank pivot. */
export const GROUND = "G";
export const CRANK_PIVOT = "P";
export const CRANK_TIP = "C";

export interface LinkSegment {
	a: string;
	b: string;
	kind: "crank" | "link";
}

/** Bars to draw: the crank (pivot P to tip C) and, for every joint, one bar from each circle centre to the joint. */
export function linkSegments(spec: LinkageSpec): LinkSegment[] {
	const segs: LinkSegment[] = [{ a: CRANK_PIVOT, b: CRANK_TIP, kind: "crank" }];
	for (const j of spec.joints) {
		for (const c of j.centers) segs.push({ a: c, b: j.id, kind: "link" });
	}
	return segs;
}

/** What a handle edits: a named length shared by every place that uses it, or a number written inline in the spec. */
export interface LengthHandle {
	/** stable key: the param name, or a path such as "crank.x" / "joint:K.radii.0" for inline numbers */
	key: string;
	/** short label: the param name, or the inline path */
	label: string;
	/** where it is used, e.g. "G–K" (bar from G to K) or "crank.length" */
	uses: string[];
	group: "crank" | "links";
	/** current value */
	value: number;
	/** reasonable slider range: lengths stay positive, crank pivot coordinates may be negative */
	range: [number, number];
}

function span(v: number): number {
	return Math.max(100, Math.ceil((2 * Math.abs(v)) / 10) * 10);
}

/** Every adjustable length of a spec, in a stable order: crank first, then bars in joint order. */
export function lengthHandles(spec: LinkageSpec): LengthHandle[] {
	const handles = new Map<string, LengthHandle>();
	const add = (
		ref: ParamRef,
		inlineKey: string,
		use: string,
		group: "crank" | "links",
		signed: boolean,
	) => {
		const key = typeof ref === "string" ? ref : inlineKey;
		const value = typeof ref === "string" ? spec.params[ref] : ref;
		if (value === undefined) return; // an unknown param name: validation reports it, a slider cannot edit it
		const have = handles.get(key);
		if (have) {
			if (!have.uses.includes(use)) have.uses.push(use);
			return;
		}
		const s = span(value);
		handles.set(key, {
			key,
			label: typeof ref === "string" ? ref : inlineKey,
			uses: [use],
			group,
			value,
			range: signed ? [-s, s] : [0.1, s],
		});
	};
	add(spec.crank.x, "crank.x", "crank.x", "crank", true);
	add(spec.crank.y, "crank.y", "crank.y", "crank", true);
	add(spec.crank.length, "crank.length", "crank.length", "crank", false);
	for (const j of spec.joints) {
		j.radii.forEach((r, i) => {
			const use = `${j.centers[i]}–${j.id}`;
			add(r, `joint:${j.id}.radii.${i}`, use, "links", false);
		});
	}
	for (const [name, value] of Object.entries(spec.params)) {
		if (!handles.has(name))
			handles.set(name, {
				key: name,
				label: name,
				uses: [],
				group: "links",
				value,
				range: [0.1, span(value)],
			});
	}
	return [...handles.values()];
}

/** A copy of `spec` with one length changed (a named param, or an inline number addressed by its handle key). */
export function withLength(
	spec: LinkageSpec,
	key: string,
	value: number,
): LinkageSpec {
	const out: LinkageSpec = JSON.parse(JSON.stringify(spec));
	if (key in out.params) {
		out.params[key] = value;
		return out;
	}
	if (key === "crank.x" || key === "crank.y" || key === "crank.length") {
		out.crank[key.slice(6) as "x" | "y" | "length"] = value;
		return out;
	}
	const m = /^joint:(.+)\.radii\.(\d)$/.exec(key);
	const joint = m && out.joints.find((j) => j.id === m[1]);
	if (!m || !joint) throw new Error(`unknown length: ${key}`);
	joint.radii[Number(m[2])] = value;
	return out;
}

/** Points that must be on screen: the crank pivot and the ground pivot at the origin. */
export function crankPivot(spec: LinkageSpec): { x: number; y: number } {
	const v = (r: ParamRef) =>
		typeof r === "number" ? r : (spec.params[r] as number);
	return { x: v(spec.crank.x), y: v(spec.crank.y) };
}

/** The named lengths of a spec in declaration order: the coordinates of a genome for optimisation. */
export function paramNames(spec: LinkageSpec): string[] {
	return Object.keys(spec.params);
}
