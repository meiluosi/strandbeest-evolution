import type { SimConfig } from "./config";

/** Run.audit_observation: every driven step, independent of telemetry cadence. */
export interface AuditObservationDocument {
	version: 1;
	scope: "driven_steps_excluding_settle";
	boundary: "force_evaluation" | "post_step";
	timestep_s: number;
	legs: number;
	support_force_N: 0.000001;
	integration_steps: number;
	observed_steps: number;
	invalid_steps: number;
	time_gap_steps: number;
	airborne_steps: number;
	first_time_s: number | null;
	last_time_s: number | null;
	max_loop_residual_m: number | null;
	max_penetration_m: number | null;
}

const SUPPORT_FORCE_N = 1e-6;
const ROUND_OFF = 128 * Number.EPSILON;

const finite = (value: unknown): value is number =>
	typeof value === "number" && Number.isFinite(value);

const OBSERVATION_KEYS = [
	"version",
	"scope",
	"boundary",
	"timestep_s",
	"legs",
	"support_force_N",
	"integration_steps",
	"observed_steps",
	"invalid_steps",
	"time_gap_steps",
	"airborne_steps",
	"first_time_s",
	"last_time_s",
	"max_loop_residual_m",
	"max_penetration_m",
] as const;

function matchesObservationSchema(
	value: unknown,
): value is Record<keyof AuditObservationDocument, unknown> {
	if (typeof value !== "object" || value === null || Array.isArray(value))
		return false;
	const o = value as Record<string, unknown>;
	const keys = Object.keys(o);
	if (
		keys.length !== OBSERVATION_KEYS.length ||
		!OBSERVATION_KEYS.every((k) => Object.hasOwn(o, k))
	)
		return false;
	if (o.version !== 1 || o.scope !== "driven_steps_excluding_settle")
		return false;
	if (o.boundary !== "force_evaluation" && o.boundary !== "post_step")
		return false;
	if (
		typeof o.timestep_s !== "number" ||
		(Number.isFinite(o.timestep_s) && o.timestep_s <= 0)
	)
		return false;
	if (
		typeof o.legs !== "number" ||
		(Number.isFinite(o.legs) && (!Number.isInteger(o.legs) || o.legs < 1))
	)
		return false;
	if (o.support_force_N !== SUPPORT_FORCE_N) return false;
	for (const k of [
		"integration_steps",
		"observed_steps",
		"invalid_steps",
		"time_gap_steps",
		"airborne_steps",
	] as const) {
		const v = o[k];
		if (
			typeof v !== "number" ||
			(Number.isFinite(v) && (!Number.isInteger(v) || v < 0))
		)
			return false;
	}
	for (const k of [
		"first_time_s",
		"last_time_s",
		"max_loop_residual_m",
		"max_penetration_m",
	] as const) {
		const v = o[k];
		if (v !== null && (typeof v !== "number" || (Number.isFinite(v) && v < 0)))
			return false;
	}
	return true;
}

export class AuditObservation {
	private value: Omit<AuditObservationDocument, "integration_steps">;

	constructor(
		timestep: number,
		legs: number,
		boundary: AuditObservationDocument["boundary"],
	) {
		if (
			!finite(timestep) ||
			timestep <= 0 ||
			!Number.isInteger(legs) ||
			legs < 1
		)
			throw new Error(
				"Audit observations require a positive timestep and leg count",
			);
		if (boundary !== "force_evaluation" && boundary !== "post_step")
			throw new Error("Unknown observation boundary");
		this.value = {
			version: 1,
			scope: "driven_steps_excluding_settle",
			boundary,
			timestep_s: timestep,
			legs,
			support_force_N: 0.000001,
			observed_steps: 0,
			invalid_steps: 0,
			time_gap_steps: 0,
			airborne_steps: 0,
			first_time_s: null,
			last_time_s: null,
			max_loop_residual_m: null,
			max_penetration_m: null,
		};
	}

	observe(time: number, normal: number[], loop: number, penetration: number) {
		const v = this.value;
		v.observed_steps++;
		const validTime = finite(time) && time >= 0;
		if (validTime) {
			const expected =
				v.last_time_s === null
					? v.boundary === "force_evaluation"
						? 0
						: v.timestep_s
					: v.last_time_s + v.timestep_s;
			if (
				Math.abs(time - expected) >
				ROUND_OFF * Math.max(Math.abs(time), Math.abs(expected), v.timestep_s)
			)
				v.time_gap_steps++;
			if (v.first_time_s === null) v.first_time_s = time;
			v.last_time_s = time;
		}
		const validLoads =
			Array.isArray(normal) &&
			normal.length === v.legs &&
			normal.every((f) => finite(f) && f >= 0);
		if (validLoads && !normal.some((f) => f > v.support_force_N))
			v.airborne_steps++;
		let valid = validTime && validLoads;
		for (const [name, value] of [
			["max_loop_residual_m", loop],
			["max_penetration_m", penetration],
		] as const) {
			if (finite(value) && value >= 0)
				v[name] = v[name] === null ? value : Math.max(v[name], value);
			else valid = false;
		}
		if (!valid) v.invalid_steps++;
	}

	document(integrationSteps: number): AuditObservationDocument {
		return { ...this.value, integration_steps: integrationSteps };
	}
}

/** Check coverage, Scenario identity and contradictions in recorded samples.
 *  Port of strandbeest_sim.audit_observation.observation_issues.
 */
export function observationIssues(
	sc: SimConfig,
	metrics: Record<string, unknown>,
	series: Record<string, unknown> | null | undefined,
	observation: unknown,
	backendName: string | null = null,
): string[] {
	if (observation === null || observation === undefined)
		return ["missing_all_step_observation"];
	if (!matchesObservationSchema(observation))
		return ["invalid_observation_contract"];
	if (
		Object.values(observation).some(
			(v) => typeof v === "number" && !Number.isFinite(v),
		)
	)
		return ["nonfinite_observation"];
	const o = observation as unknown as AuditObservationDocument;
	const issues: string[] = [];
	const n = o.integration_steps;
	if (
		!n ||
		o.observed_steps !== n ||
		o.invalid_steps > 0 ||
		o.time_gap_steps > 0 ||
		o.airborne_steps > n
	)
		issues.push("incomplete_or_invalid_steps");
	if (o.legs !== sc.walker.legs || o.timestep_s !== sc.solver.timestep)
		issues.push("scenario_mismatch");
	const boundary =
		backendName === "mujoco"
			? "force_evaluation"
			: backendName === "k2"
				? "post_step"
				: undefined;
	if (boundary !== undefined && o.boundary !== boundary)
		issues.push("backend_boundary_mismatch");
	const first = o.first_time_s;
	const last = o.last_time_s;
	const dt = o.timestep_s;
	const expectedFirst = o.boundary === "force_evaluation" ? 0 : dt;
	let bound = 0;
	if (!finite(first) || !finite(last)) {
		issues.push("missing_observation_times");
	} else {
		bound = ROUND_OFF * Math.max(n, 1) * Math.max(Math.abs(last), dt);
		if (
			first !== expectedFirst ||
			last < first ||
			Math.abs(last - first - (n - 1) * dt) > bound
		)
			issues.push("inconsistent_observation_times");
	}
	for (const [key, metric] of [
		["max_loop_residual_m", "max_loop_violation"],
		["max_penetration_m", "max_penetration"],
	] as const) {
		const mv = metrics[metric];
		if (!finite(o[key]) || !finite(mv) || mv !== o[key])
			issues.push(`inconsistent_${metric}`);
	}
	if (issues.length > 0) return issues;
	if (series === null || series === undefined) return [];
	if (typeof series !== "object" || Array.isArray(series))
		return ["missing_or_invalid_recorded_samples"];
	const t = series.t;
	const normal = series.foot_normal;
	const loop = series.loop_residual;
	const penetration = series.penetration;
	if (
		!Array.isArray(t) ||
		!Array.isArray(normal) ||
		!Array.isArray(loop) ||
		!Array.isArray(penetration)
	)
		return ["missing_or_invalid_recorded_samples"];
	const count = Math.floor((n + sc.run.record_every - 1) / sc.run.record_every);
	const valid1D = (a: unknown[], nonneg = false): a is number[] =>
		a.length === count && a.every((v) => finite(v) && (!nonneg || v >= 0));
	const validNormal = (a: unknown[]): a is number[][] =>
		a.length === count &&
		a.every(
			(row) =>
				Array.isArray(row) &&
				row.length === sc.walker.legs &&
				row.every((v) => finite(v) && v >= 0),
		);
	if (
		!valid1D(t) ||
		!valid1D(loop, true) ||
		!valid1D(penetration) ||
		!validNormal(normal)
	)
		return ["invalid_or_incomplete_recorded_samples"];
	const firstTime = first as number;
	let timeDisagrees = false;
	for (let i = 0; i < count; i++) {
		const expectedT = firstTime + i * sc.run.record_every * dt;
		if (Math.abs((t[i] as number) - expectedT) > bound) {
			timeDisagrees = true;
			break;
		}
		if (i > 0 && (t[i] as number) <= (t[i - 1] as number)) {
			timeDisagrees = true;
			break;
		}
	}
	if (timeDisagrees) issues.push("recorded_times_disagree");
	let sparseAirborne = 0;
	for (const row of normal) {
		if (row.every((f) => f <= SUPPORT_FORCE_N)) sparseAirborne++;
	}
	if (
		sparseAirborne > o.airborne_steps ||
		count - sparseAirborne > n - o.airborne_steps
	)
		issues.push("recorded_support_disagrees");
	for (const [arr, key] of [
		[loop, "max_loop_residual_m"],
		[penetration, "max_penetration_m"],
	] as const) {
		let maxVal = 0;
		for (const v of arr) if (v > maxVal) maxVal = v;
		const target = o[key] as number;
		if (maxVal > target || (sc.run.record_every === 1 && maxVal !== target))
			issues.push(`recorded_${key}_disagrees`);
	}
	if (sc.run.record_every === 1 && sparseAirborne !== o.airborne_steps)
		issues.push("full_support_disagrees");
	return issues;
}
