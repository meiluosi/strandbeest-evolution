/** The flat simulator configuration (schemas/scenario-v1.schema.json). Defaults are read from the schema, not copied. */
import schema from "../../../schemas/scenario-v1.schema.json";

export interface Walker {
	legs: number;
	mass: number;
	body_mass: number | null;
	unit: number;
	direction: -1 | 1;
	tube_mass_per_m: number;
	min_bar_mass: number;
	lateral_spacing: number;
	body_length: number;
	pitch: "free" | "locked";
	bar_radius: number;
	foot_radius: number;
	foot_friction: number;
	joint_friction: number;
	joint_damping: number;
}
export interface Drive {
	kind: string;
	omega: number;
	kp: number;
	max_torque: number | null;
	kv: number;
	ramp: number;
	[k: string]: unknown;
}
export interface Solver {
	timestep: number;
	iterations: number;
	contact_solref: number;
	contact_stiffness: number | null;
	contact_damping_ratio: number;
	cone: string;
	impratio: number;
	noslip_iterations: number;
	solref_time: number;
	solimp: string;
}
export interface Terrain {
	kind: string;
	friction: number;
	slope_deg: number;
	params: Record<string, unknown>;
}
export interface Run {
	settle: number;
	revolutions: number;
	max_time: number;
	record_every: number;
	frame_rate: number;
	give_up_after: number;
}
export interface SimConfig {
	name: string;
	linkage: { spec: unknown; params: Record<string, number> };
	walker: Walker;
	environment: { gravity: number; air_density: number };
	wind: { kind: string; speed: number; params: Record<string, unknown> };
	terrain: Terrain;
	drive: Drive;
	solver: Solver;
	run: Run;
}

type Raw = Record<string, unknown>;
const defs = (
	schema as unknown as {
		$defs: Record<
			string,
			{ properties: Record<string, { default?: unknown }> }
		>;
	}
).$defs;
const SECTIONS = [
	"linkage",
	"walker",
	"environment",
	"wind",
	"terrain",
	"drive",
	"solver",
	"run",
] as const;
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function defaultsOf(section: string): Raw {
	const out: Raw = {};
	const def = defs[section[0]?.toUpperCase() + section.slice(1)];
	for (const [k, p] of Object.entries(def?.properties ?? {}))
		if ("default" in p) out[k] = clone(p.default);
	return out;
}

/** Fill every section of a flat scenario with the schema defaults (what pydantic does for `SimConfig.model_validate`). */
export function simConfig(raw: Raw): SimConfig {
	const out: Raw = { name: raw.name ?? "unnamed" };
	for (const s of SECTIONS)
		out[s] = { ...defaultsOf(s), ...((raw[s] as Raw | undefined) ?? {}) };
	return out as unknown as SimConfig;
}
