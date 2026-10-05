/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fitnessFlatStroke } from "./fitness";
import { runGA } from "./ga";
import { genomeSpace, JANSEN_SPACE } from "./genome";
import { jansenSpec } from "./jansen";
import { type LinkageSpec, trace } from "./linkage";
import { lengthHandles, linkSegments, withLength } from "./structure";
import { structureErrors } from "./validity";

const dir = join(import.meta.dirname, "../../../contracts/kinematics");
const corpus: Record<string, LinkageSpec> = Object.fromEntries(
	readdirSync(dir)
		.filter((f) => f.endsWith(".json"))
		.map((f) => {
			const doc = JSON.parse(readFileSync(join(dir, f), "utf8"));
			return [doc.name as string, doc.spec as LinkageSpec];
		}),
);

// What LinkageViewer used to hard-code for Jansen's leg.
const OLD_JANSEN_LINKS = [
	"P-C",
	"G-K",
	"K-C",
	"G-L",
	"K-L",
	"G-M",
	"C-M",
	"L-N",
	"M-N",
	"M-F",
	"N-F",
];
const OLD_JANSEN_ROLES: Record<string, string> = {
	b: "G–K",
	j: "C–K",
	d: "G–L",
	e: "K–L",
	c: "G–M",
	k: "C–M",
	f: "L–N",
	g: "M–N",
	i: "M–F",
	h: "N–F",
};

describe("structure derived from the spec", () => {
	it("reproduces Jansen's hard-coded bar list and slider roles", () => {
		const bars = linkSegments(jansenSpec()).map((s) =>
			[s.a, s.b].sort().join("-"),
		);
		expect(bars.sort()).toEqual(
			OLD_JANSEN_LINKS.map((l) => l.split("-").sort().join("-")).sort(),
		);
		const handles = lengthHandles(jansenSpec());
		expect(handles).toHaveLength(13);
		expect(
			handles.filter((h) => h.group === "crank").map((h) => h.key),
		).toEqual(["a", "l", "m"]);
		for (const [name, role] of Object.entries(OLD_JANSEN_ROLES))
			expect(handles.find((h) => h.key === name)?.uses).toEqual([role]);
	});

	it("handles any dyad chain in the corpus: one bar pair per joint, one slider per length", () => {
		expect(Object.keys(corpus).length).toBeGreaterThanOrEqual(4);
		for (const [name, spec] of Object.entries(corpus)) {
			expect(linkSegments(spec), name).toHaveLength(1 + 2 * spec.joints.length);
			const keys = lengthHandles(spec).map((h) => h.key);
			for (const p of Object.keys(spec.params))
				expect(keys, `${name}: ${p}`).toContain(p);
			// every drawn endpoint is a known point
			const known = new Set(["G", "P", "C", ...spec.joints.map((j) => j.id)]);
			for (const s of linkSegments(spec)) {
				expect(known.has(s.a) && known.has(s.b), `${name}: ${s.a}-${s.b}`).toBe(
					true,
				);
			}
		}
	});

	it("exposes inline numbers as handles and edits them without touching named lengths", () => {
		const spec: LinkageSpec = {
			params: { a: 40, l: 0, m: 10, b: 45 },
			crank: { x: "a", y: "l", length: "m" },
			joints: [{ id: "K", centers: ["G", "C"], radii: ["b", 38], side: 1 }],
			foot: "K",
		};
		const h = lengthHandles(spec);
		const inline = h.find((x) => x.key === "joint:K.radii.1");
		expect(inline).toMatchObject({ value: 38, group: "links", uses: ["C–K"] });
		const edited = withLength(spec, "joint:K.radii.1", 36);
		expect(edited.joints[0]?.radii).toEqual(["b", 36]);
		expect(edited.params).toEqual(spec.params);
		expect(spec.joints[0]?.radii[1]).toBe(38); // the input is not mutated
		expect(withLength(spec, "b", 44).params.b).toBe(44);
		expect(withLength(spec, "crank.x", 41).crank.x).toBe(41);
		expect(() => withLength(spec, "nope", 1)).toThrow();
	});

	it("gives slider ranges that contain the value and keep bar lengths positive", () => {
		for (const spec of [jansenSpec(), ...Object.values(corpus)])
			for (const h of lengthHandles(spec)) {
				expect(h.range[0]).toBeLessThanOrEqual(h.value);
				expect(h.range[1]).toBeGreaterThanOrEqual(h.value);
				if (h.group === "links") expect(h.range[0]).toBeGreaterThan(0);
			}
	});
});

describe("genome space over any topology", () => {
	it("round-trips a spec through its genome", () => {
		for (const spec of [jansenSpec(), ...Object.values(corpus)]) {
			const space = genomeSpace(spec);
			expect(space.toSpec(space.toGenome())).toEqual(spec);
			expect(space.toGenome()).toHaveLength(Object.keys(spec.params).length);
		}
		expect(JANSEN_SPACE.names).toHaveLength(13);
	});

	it("rejects a genome of the wrong length", () => {
		expect(() => JANSEN_SPACE.toSpec([1, 2, 3])).toThrow();
	});

	it("runs the genetic algorithm on a non-Jansen chain: reproducible, never worse than the start", () => {
		const spec = corpus["sixbar-extra-dyad"] as LinkageSpec;
		const space = genomeSpace(spec);
		const fit = fitnessFlatStroke(space);
		const opts = { seed: 3, population: 16, generations: 6 };
		const start = space.toGenome();
		const a = runGA(start, fit, opts);
		const b = runGA(start, fit, opts);
		expect(a.best).toEqual(b.best);
		expect(a.bestFitness).toBeGreaterThanOrEqual(fit(start));
		expect(trace(space.toSpec(a.best), 90).foot.length).toBe(90);
	});
});

describe("static validity (contract shared with Python)", () => {
	const cases = JSON.parse(
		readFileSync(
			join(
				import.meta.dirname,
				"../../../contracts/linkage-structure/cases.json",
			),
			"utf8",
		),
	).cases as {
		name: string;
		spec: LinkageSpec;
		errors: { code: string; path: string }[];
	}[];
	for (const c of cases) {
		it(c.name, () => {
			expect(
				structureErrors(c.spec).map(({ code, path }) => ({ code, path })),
			).toEqual(c.errors);
		});
	}
	it("accepts Jansen's leg and every kinematics contract", () => {
		expect(structureErrors(jansenSpec())).toEqual([]);
		for (const [name, spec] of Object.entries(corpus))
			expect(structureErrors(spec), name).toEqual([]);
	});
});
