import { type Design, makeGuard, schemaProblems } from "strandbeest-core";
import atlasSchema from "../../../schemas/atlas.schema.json";
import designSchema from "../../../schemas/design.schema.json";
import { type Job, runJob } from "./api";

const designGuard = makeGuard(designSchema);

export interface EliteCellData {
	cell: number[];
	fitness: number;
	lift_ratio?: number;
	cost_of_transport?: number;
	features?: Record<string, number>;
	genome: number[];
	legs?: number;
	stride_m?: number;
	mass_kg?: number;
	born: number;
	parent?: number[] | null;
	design?: Design;
}

export interface AtlasDoc {
	schema_version: number;
	kind: string;
	id: string;
	name?: string;
	created: string;
	base_design_id: string;
	dimensions: number;
	features: string[];
	feature_labels?: string[];
	feature_ranges?: Record<string, [number, number]>;
	grid_shape: number[];
	cells_total: number;
	cells_filled: number;
	coverage: number;
	qd_score: number;
	best_fitness?: number;
	evals: number;
	pareto_front?: number[][];
	cells: EliteCellData[];
}

export class AtlasValidationError extends Error {
	constructor(public field: string) {
		super(field);
	}
}

function reject(field: string): never {
	throw new AtlasValidationError(field);
}

function finiteNumbers(value: unknown, path = ""): void {
	if (typeof value === "number" && !Number.isFinite(value)) reject(path);
	if (value && typeof value === "object")
		for (const [key, child] of Object.entries(value))
			finiteNumbers(child, path ? `${path}.${key}` : key);
}

/** Validate both the shared schema and the archive's cross-field invariants. */
export function parseAtlas(value: unknown): AtlasDoc {
	finiteNumbers(value);
	const problems = schemaProblems(atlasSchema, value);
	if (problems.length) reject(problems[0]?.path ?? "atlas");
	const atlas = value as AtlasDoc;
	const { dimensions, grid_shape: shape, cells } = atlas;
	if (dimensions < 2 || shape.length !== dimensions) reject("dimensions");
	if (
		atlas.features.length !== dimensions ||
		new Set(atlas.features).size !== dimensions
	)
		reject("features");
	if (shape.some((n) => !Number.isSafeInteger(n) || n < 1 || n > 10000))
		reject("grid_shape");
	const total = shape.reduce((product, n) => product * n, 1);
	if (!Number.isSafeInteger(total) || total !== atlas.cells_total)
		reject("cells_total");
	// Keep imported files from expanding an unbounded SVG in the browser.
	if ((shape[0] ?? 0) * (shape[1] ?? 0) > 10000) reject("grid_shape");
	const coordinateValid = (coord: number[]) =>
		coord.length === dimensions &&
		coord.every((n, i) => Number.isInteger(n) && n >= 0 && n < (shape[i] ?? 0));
	const seen = new Set<string>();
	for (const [i, elite] of cells.entries()) {
		if (!coordinateValid(elite.cell) || seen.has(elite.cell.join(",")))
			reject(`cells.${i}.cell`);
		seen.add(elite.cell.join(","));
		if (elite.parent && !coordinateValid(elite.parent))
			reject(`cells.${i}.parent`);
		if (elite.design && schemaProblems(designSchema, elite.design).length)
			reject(`cells.${i}.design`);
	}
	if (atlas.cells_filled !== cells.length) reject("cells_filled");
	if (Math.abs(atlas.coverage - cells.length / total) > 1e-9)
		reject("coverage");
	const score = cells.reduce((sum, elite) => sum + elite.fitness, 0);
	if (Math.abs(atlas.qd_score - score) > 1e-9 * Math.max(1, Math.abs(score)))
		reject("qd_score");
	const best = cells.length ? Math.max(...cells.map((c) => c.fitness)) : 0;
	if (
		atlas.best_fitness !== undefined &&
		Math.abs(atlas.best_fitness - best) > 1e-9
	)
		reject("best_fitness");
	for (const coord of atlas.pareto_front ?? [])
		if (!coordinateValid(coord) || !seen.has(coord.join(",")))
			reject("pareto_front");
	for (const [feature, range] of Object.entries(atlas.feature_ranges ?? {}))
		if (range[0] >= range[1]) reject(`feature_ranges.${feature}`);
	return atlas;
}

/** The first two axes remain visible; each remaining coordinate selects a slice. */
export function atlasSlice(
	atlas: AtlasDoc,
	tail: readonly number[],
): EliteCellData[] {
	return atlas.cells.filter((elite) =>
		elite.cell.slice(2).every((n, i) => n === (tail[i] ?? 0)),
	);
}

export function bestAtlasCell(atlas: AtlasDoc): EliteCellData | null {
	return atlas.cells.reduce<EliteCellData | null>(
		(best, elite) => (!best || elite.fitness > best.fitness ? elite : best),
		null,
	);
}

export const FEATURE_KEYS: Record<string, string> = {
	lift_ratio: "map_elites.axisLift",
	cost_of_transport: "map_elites.axisCost",
	stability_margin: "map_elites.axisStability",
	legs: "map_elites.axisLegs",
	stride: "map_elites.axisStride",
	mass: "map_elites.axisMass",
};

export function eliteFeature(
	elite: EliteCellData,
	name: string,
): number | undefined {
	const aliases: Record<string, number | undefined> = {
		legs: elite.legs,
		stride: elite.stride_m,
		mass: elite.mass_kg,
		lift_ratio: elite.lift_ratio,
		cost_of_transport: elite.cost_of_transport,
	};
	return elite.features?.[name] ?? aliases[name];
}

/** JSON assets may be wrapped in Svelte proxies after a job/import updates state. */
export function eliteDesign(elite: EliteCellData): Design | null {
	if (!elite.design) return null;
	if (designGuard(elite.design).some((problem) => problem.level === "error"))
		reject("design");
	return JSON.parse(JSON.stringify(elite.design)) as Design;
}

/** runJob resolves directly to the atlas, not a job wrapper. */
export async function evolveAtlas(
	design: Design,
	onTick?: (job: Job) => void,
	seed = 42,
): Promise<AtlasDoc> {
	if (designGuard(design).some((problem) => problem.level === "error"))
		reject("design");
	const result = await runJob<unknown>(
		"/evolve/qd",
		{
			design,
			evals: 200,
			bins: [15, 15],
			feature_descriptors: ["lift_ratio", "cost_of_transport"],
			seed,
		},
		onTick,
	);
	return parseAtlas(result);
}
