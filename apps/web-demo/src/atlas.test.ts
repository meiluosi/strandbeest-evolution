import { defaultDesign, schemaProblems } from "strandbeest-core";
import { afterEach, describe, expect, it, vi } from "vitest";
import designSchema from "../../../schemas/design.schema.json";
import {
	atlasSlice,
	bestAtlasCell,
	eliteDesign,
	eliteFeature,
	evolveAtlas,
	FEATURE_KEYS,
	parseAtlas,
} from "./atlas";
import { createTranslator } from "./i18n/core";
import en from "./i18n/en.json";
import zh from "./i18n/zh.json";
import sample from "./sample-atlas.json";

afterEach(() => vi.unstubAllGlobals());

describe("archive boundary", () => {
	it("retains every 3D cell across slices, including both elites at (1, 1)", () => {
		const atlas = parseAtlas(sample);
		const slices = Array.from({ length: atlas.grid_shape[2] ?? 0 }, (_, i) =>
			atlasSlice(atlas, [i]),
		);
		expect(slices.flat()).toHaveLength(atlas.cells_filled);
		expect(
			new Set(slices.flat().map((elite) => elite.cell.join(","))).size,
		).toBe(atlas.cells_filled);
		const best = bestAtlasCell(atlas);
		expect(best?.fitness).toBe(atlas.best_fitness);
		expect(best?.cell).toEqual([1, 1, 1]);
		expect(slices[1]?.find((elite) => elite.cell.join(",") === "1,1,1")).toBe(
			best,
		);
		expect(
			slices[0]?.find((elite) => elite.cell.join(",") === "1,1,0"),
		).not.toBe(best);
		expect(best?.design?.linkage.params).toBeDefined();
	});

	it("uses all remaining coordinates for higher dimensional slices", () => {
		const atlas = structuredClone(sample);
		atlas.dimensions = 4;
		atlas.grid_shape.push(2);
		atlas.features.push("extra");
		atlas.cells_total *= 2;
		atlas.coverage /= 2;
		for (const cell of atlas.cells) {
			cell.cell.push(cell.born % 2);
			cell.parent?.push(0);
		}
		atlas.pareto_front = [];
		const valid = parseAtlas(atlas);
		const cells = [0, 1].flatMap((z) =>
			[0, 1].flatMap((w) => atlasSlice(valid, [z, w])),
		);
		expect(cells).toHaveLength(valid.cells_filled);
	});

	it.each([
		[
			"missing contract",
			(a: any) => {
				delete a.schema_version;
			},
		],
		[
			"wrong kind",
			(a: any) => {
				a.kind = "design";
			},
		],
		[
			"unknown field",
			(a: any) => {
				a.unexpected = true;
			},
		],
		[
			"dimension mismatch",
			(a: any) => {
				a.dimensions = 2;
			},
		],
		[
			"duplicate coordinate",
			(a: any) => {
				a.cells[1].cell = a.cells[0].cell;
			},
		],
		[
			"out of bounds",
			(a: any) => {
				a.cells[0].cell[0] = a.grid_shape[0];
			},
		],
		[
			"nonpositive shape",
			(a: any) => {
				a.grid_shape[0] = 0;
			},
		],
		[
			"nonfinite result",
			(a: any) => {
				a.cells[0].fitness = Infinity;
			},
		],
		[
			"misleading statistics",
			(a: any) => {
				a.best_fitness = 100;
			},
		],
		[
			"invalid design",
			(a: any) => {
				a.cells[0].design = { linkage: {} };
			},
		],
		[
			"missing Pareto cell",
			(a: any) => {
				a.pareto_front.push([0, 0, 0]);
			},
		],
	])("rejects %s before rendering or loading", (_, mutate) => {
		const invalid = structuredClone(sample);
		mutate(invalid);
		expect(() => parseAtlas(invalid)).toThrow();
	});

	it("labels actual descriptors in either language and leaves absent metrics missing", () => {
		const best = bestAtlasCell(parseAtlas(sample));
		if (!best) throw new Error("sample has no elites");
		expect(eliteFeature(best, "stride")).toBe(best.stride_m);
		expect(eliteFeature(best, "mass")).toBe(best.mass_kg);
		expect(eliteFeature(best, "stability_margin")).toBeUndefined();
		const translations = (["zh", "en"] as const).map((locale) => {
			const t = createTranslator({ zh, en }, locale);
			return sample.features.map((name) => t(FEATURE_KEYS[name] ?? ""));
		});
		expect(translations[0]).not.toEqual(translations[1]);
		expect(translations.flat().every(Boolean)).toBe(true);
	});
});

it("loads a job result wrapped in a reactive proxy without sharing editor mutations", () => {
	const elite = structuredClone(parseAtlas(sample).cells[0]!);
	if (!elite.design) throw new Error("missing design");
	const design = new Proxy(elite.design, {});
	expect(() => structuredClone(design)).toThrow();
	const loaded = eliteDesign({ ...elite, design });
	expect(loaded).toEqual(design);
	expect(loaded).not.toBe(design);
	if (!loaded) throw new Error("missing design");
	loaded.linkage.params.a = 999;
	expect(elite.design.linkage.params.a).not.toBe(999);
});

describe("evolution job integration", () => {
	it("rejects an unassemblable design before submitting or opening it", async () => {
		const design = defaultDesign();
		design.linkage.params.m = 1000;
		const fetchSpy = vi.fn();
		vi.stubGlobal("fetch", fetchSpy);
		await expect(evolveAtlas(design)).rejects.toThrow("design");
		expect(fetchSpy).not.toHaveBeenCalled();
		const elite = parseAtlas(sample).cells[0]!;
		expect(() => eliteDesign({ ...elite, design })).toThrow("design");
	});

	it("submits the current Design and consumes runJob's bare atlas result", async () => {
		const design = defaultDesign();
		design.linkage.params.a = 39;
		const result = structuredClone(sample);
		result.base_design_id = design.id;
		const requests: { path: string; body: any }[] = [];
		vi.stubGlobal(
			"fetch",
			vi.fn(async (url: string, init: RequestInit) => {
				const path = new URL(url).pathname;
				const body = init.body ? JSON.parse(String(init.body)) : undefined;
				requests.push({ path, body });
				if (path === "/evolve/qd") {
					// This is the API boundary that the old UI violated (422 without design).
					if (!body.design || schemaProblems(designSchema, body.design).length)
						return Response.json(
							{ detail: "design required" },
							{ status: 422 },
						);
					return Response.json({ job_id: "qd-job" });
				}
				return Response.json({
					id: "qd-job",
					status: "done",
					result,
					progress: { done: 200, total: 200, message: "" },
				});
			}),
		);
		const progress: string[] = [];
		const atlas = await evolveAtlas(
			design,
			(job) => progress.push(job.status),
			123,
		);
		expect(requests[0]?.body.design).toEqual(design);
		expect(requests[0]?.body.seed).toBe(123);
		expect(requests[0]?.body.bins).toEqual([15, 15]);
		expect(requests.map((r) => r.path)).toEqual(["/evolve/qd", "/jobs/qd-job"]);
		expect(atlas).toEqual(result);
		expect(progress).toEqual(["queued", "done"]);
		const selected = bestAtlasCell(atlas);
		expect(selected?.design).toBeDefined();
		expect(schemaProblems(designSchema, selected?.design)).toEqual([]);
	});

	it("rejects a malformed completed result instead of silently keeping the old archive", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn(async (url: string) =>
				Response.json(
					url.endsWith("/evolve/qd")
						? { job_id: "bad" }
						: { status: "done", result: { atlas: sample } },
				),
			),
		);
		await expect(evolveAtlas(defaultDesign())).rejects.toThrow();
	});
});
