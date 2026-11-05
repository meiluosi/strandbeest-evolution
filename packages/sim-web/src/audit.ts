/** Versioned simulation audit with explicit reference applicability (ADR-0012).
 *  Port of strandbeest_sim.audit and strandbeest_sim.skeptic.
 *
 *  The geometric model is an exact-constraint limit. We do not invent a nonzero
 *  physical tolerance for slip/compliance to make it apply to a compliant run.
 *  Those runs need an independent dynamical/measurement comparison; absent such
 *  evidence, the result remains unverified. A pass here never upgrades E0 to E1-E3.
 */
import {
	type StrideReference,
	solvePose,
	strideReference,
} from "strandbeest-core";
import { observationIssues } from "./audit-observation";
import { buildMjcf, resolveSpec } from "./builder";
import type { SimConfig } from "./config";
import { nominalStrideM } from "./events";

export const ENERGY_RESIDUAL = 0.02;
export const LOOP_OPEN_M = 0.005;
export const PENETRATION_M = 0.005;
export const STRIDE_TOLERANCE = 0.15;
export const SUPPORT_FORCE_N = 1e-6;
const RESOLUTIONS = [720, 1440] as const;
const REFERENCE_NUMERICAL_RELATIVE_TOLERANCE = 1e-6;

export interface AuditFinding {
	check: string;
	message: string;
	evidence: Record<string, unknown>;
}

export interface AuditCondition {
	code: string;
	status: "verified" | "unverified";
	evidence: Record<string, unknown>;
}

export interface FootSphereOwner {
	leg: number;
	start: string;
	end: string;
	radius_m: number;
}

export interface IndependentValidationSummary {
	status: "verified" | "unverified" | "failed";
	backend: string;
	stride_m_per_rev: number | null;
	relative_difference: number | null;
	relative_tolerance: typeof STRIDE_TOLERANCE;
	provenance?: Record<string, unknown>;
}

export interface StrideReferenceSummary {
	model: "lowest-foot-sphere-v1";
	signed_stride_m_per_rev: number | null;
	numerically_resolved: boolean;
	owners?: FootSphereOwner[];
	resolutions?: number[];
	samples?: StrideReference[];
	resolution_relative_difference?: number | null;
	resolution_relative_tolerance?: number;
	error?: string;
	applicability?: "verified" | "unverified";
	conditions?: AuditCondition[];
	comparison?: {
		relative_error: number | null;
		relative_tolerance: typeof STRIDE_TOLERANCE;
		diagnostic_only: boolean;
	};
	independent_validation?: IndependentValidationSummary;
}

export interface SimulationAuditReport {
	version: 2;
	status: "passed" | "failed" | "unverified";
	passed: boolean;
	scope: "numerical_invariants_and_applicable_geometric_reference";
	physical_validation_implied: false;
	thresholds: {
		energy_residual: typeof ENERGY_RESIDUAL;
		loop_open_m: typeof LOOP_OPEN_M;
		penetration_m: typeof PENETRATION_M;
		stride_relative: typeof STRIDE_TOLERANCE;
	};
	findings: AuditFinding[];
	stride_reference: StrideReferenceSummary & {
		applicability: "verified" | "unverified";
		conditions: AuditCondition[];
		comparison: {
			relative_error: number | null;
			relative_tolerance: typeof STRIDE_TOLERANCE;
			diagnostic_only: boolean;
		};
		independent_validation?: IndependentValidationSummary;
	};
	independent_validation?: IndependentValidationSummary;
	legacy: {
		version: 1;
		passed: boolean;
		findings: AuditFinding[];
	};
}

function finiteNumber(value: unknown): value is number {
	return typeof value === "number" && Number.isFinite(value);
}

function evidenceValue(value: unknown): unknown {
	if (finiteNumber(value)) return value;
	if (value === null || typeof value === "string" || typeof value === "boolean")
		return value;
	return String(value);
}

/** Version 1 audit, retained unchanged for historical comparisons (ADR-0012). */
export function auditLegacy(
	sc: SimConfig,
	metrics: Record<string, unknown>,
	series: Record<string, unknown> | null | undefined = null,
	stalled = false,
): AuditFinding[] {
	const out: AuditFinding[] = [];
	const metric = (name: string, nonnegative = false): number | null => {
		const value = metrics[name];
		if (!finiteNumber(value) || (nonnegative && value < 0)) {
			out.push({
				check: "audit_evidence",
				message: `${name} is missing or invalid; its invariant cannot be verified`,
				evidence: {
					metric: name,
					value: evidenceValue(value),
					required: nonnegative ? "finite nonnegative number" : "finite number",
				},
			});
			return null;
		}
		return value;
	};

	const window = metric("steady_window");
	if (window !== null && window !== 0 && window !== 1) {
		out.push({
			check: "audit_evidence",
			message: "steady_window must be 0 or 1",
			evidence: {
				metric: "steady_window",
				value: window,
				required: "0 or 1",
			},
		});
	}
	const steady = window === 1;
	const resid = steady ? metric("energy_residual_share") : null;
	if (steady && resid !== null && Math.abs(resid) > ENERGY_RESIDUAL) {
		out.push({
			check: "energy_closure",
			message: `energy does not close: residual ${(resid * 100).toFixed(1)}% of the input work`,
			evidence: { residual_share: resid, limit: ENERGY_RESIDUAL },
		});
	}
	const loop = metric("max_loop_violation", true);
	if (loop !== null && loop > LOOP_OPEN_M) {
		out.push({
			check: "loop_closure",
			message: `a loop opened by ${(loop * 1000).toFixed(1)} mm`,
			evidence: { opening_m: loop, limit_m: LOOP_OPEN_M },
		});
	}
	const pen = metric("max_penetration", true);
	if (pen !== null && pen > PENETRATION_M) {
		out.push({
			check: "penetration",
			message: `feet sink ${(pen * 1000).toFixed(1)} mm`,
			evidence: { penetration_m: pen, limit_m: PENETRATION_M },
		});
	}
	if (sc.terrain.kind === "flat" && sc.drive.kind === "motor" && !stalled) {
		const stride = metric("stride_per_rev");
		let nominal: number | null = null;
		try {
			nominal = nominalStrideM(sc, resolveSpec(sc));
		} catch (exc) {
			nominal = null;
			out.push({
				check: "audit_evidence",
				message: "the kinematic stride reference could not be resolved",
				evidence: {
					metric: "nominal_stride_m",
					error: exc instanceof Error ? exc.message : String(exc),
				},
			});
		}
		if (!finiteNumber(nominal) || nominal === 0) {
			if (!out.some((f) => f.evidence.metric === "nominal_stride_m")) {
				out.push({
					check: "audit_evidence",
					message: "the kinematic stride reference is undefined or zero",
					evidence: {
						metric: "nominal_stride_m",
						value: evidenceValue(nominal),
					},
				});
			}
		} else if (
			stride !== null &&
			Math.abs(stride / nominal - 1) > STRIDE_TOLERANCE
		) {
			out.push({
				check: "stride_vs_kinematics",
				message: `stride is ${Math.round((stride / nominal) * 100)}% of the kinematic stride on flat ground`,
				evidence: {
					stride_m: stride,
					nominal_m: nominal,
					ratio: evidenceValue(stride / nominal),
				},
			});
		}
	}
	if (series !== null && series !== undefined && sc.walker.legs >= 4) {
		const normal =
			typeof series === "object" && !Array.isArray(series)
				? series.foot_normal
				: null;
		const valid =
			Array.isArray(normal) &&
			normal.length > 0 &&
			normal.every(
				(row) =>
					Array.isArray(row) &&
					row.length === sc.walker.legs &&
					row.every((v) => finiteNumber(v) && v >= 0),
			);
		if (!valid) {
			out.push({
				check: "audit_evidence",
				message: "foot support samples are missing or invalid",
				evidence: {
					metric: "foot_normal",
					required: "nonempty finite nonnegative [samples, legs] array",
					legs: sc.walker.legs,
				},
			});
		} else if (steady) {
			const rows = normal as number[][];
			let airborneCount = 0;
			for (const row of rows) {
				if (!row.some((f) => f > SUPPORT_FORCE_N)) airborneCount++;
			}
			const noneDown = airborneCount / rows.length;
			if (noneDown > 0.05) {
				out.push({
					check: "support",
					message: `no foot touches the ground for ${Math.round(noneDown * 100)}% of the run`,
					evidence: { airborne_share: noneDown },
				});
			}
		}
	}
	return out;
}

function parseXmlAttrs(tag: string): Record<string, string> {
	const attrs: Record<string, string> = {};
	const attrRe = /([A-Za-z_][A-Za-z0-9_.-]*)="([^"]*)"/g;
	for (const match of tag.matchAll(attrRe)) {
		attrs[match[1]!] = match[2]!;
	}
	return attrs;
}

const referenceCache = new Map<string, StrideReferenceSummary>();

function computeReference(sc: SimConfig): StrideReferenceSummary {
	const spec = resolveSpec(sc);
	const xml = buildMjcf(sc, spec).xml;
	const owners: FootSphereOwner[] = [];
	const bodyStack: string[] = [];
	const tagRe = /<\/body>|<body\b[^>]*>|<geom\b[^>]*\/>/g;
	for (const m of xml.matchAll(tagRe)) {
		const token = m[0];
		if (token === "</body>") {
			bodyStack.pop();
			continue;
		}
		if (token.startsWith("<body")) {
			const attrs = parseXmlAttrs(token);
			bodyStack.push(attrs.name ?? "");
			continue;
		}
		const attrs = parseXmlAttrs(token);
		if (!(attrs.name ?? "").startsWith("foot_")) continue;
		const bodyName = bodyStack.at(-1) ?? "";
		const match = /^bar(\d+)_(.+)([01])$/.exec(bodyName);
		if (!match || attrs.type !== "sphere") {
			throw new Error("The built model has an unsupported foot owner or shape");
		}
		const joint = spec.joints.find((j) => j.id === match[2]);
		if (!joint) {
			throw new Error("The built model has an unsupported foot owner or shape");
		}
		owners.push({
			leg: Number.parseInt(match[1]!, 10),
			start: joint.centers[Number.parseInt(match[3]!, 10)]!,
			end: joint.id,
			radius_m: Number.parseFloat(attrs.size ?? "NaN"),
		});
	}
	const sortedLegs = owners.map((o) => o.leg).sort((a, b) => a - b);
	if (
		owners.length !== sc.walker.legs ||
		sortedLegs.some((leg, idx) => leg !== idx)
	) {
		throw new Error("The built model must have exactly one sphere per leg");
	}
	const first = owners[0]!;
	if (
		owners.some(
			(o) =>
				o.start !== first.start ||
				o.end !== spec.foot ||
				o.radius_m !== first.radius_m,
		)
	) {
		throw new Error(
			"The geometric reference requires equal spheres and owners",
		);
	}
	const phasesRad = Array.from(
		{ length: sc.walker.legs },
		(_, k) => (2 * Math.PI * k) / sc.walker.legs,
	);
	const direction: -1 | 1 = sc.walker.direction < 0 ? -1 : 1;
	const samples = RESOLUTIONS.map((n) =>
		strideReference(spec, {
			owner_start: first.start,
			phases_rad: phasesRad,
			direction,
			unit_m: sc.walker.unit,
			radius_m: first.radius_m,
			brackets: n,
		}),
	);
	const estimates = samples.map((r) =>
		r.status === "estimated" && r.estimate
			? r.estimate.contact_stride_m_per_rev
			: null,
	);
	const finite = estimates.every((v): v is number => finiteNumber(v));
	const signed = finite ? estimates.at(-1)! : null;
	const difference = finite ? Math.abs(estimates[1]! - estimates[0]!) : null;
	const relative =
		finite && signed !== null && signed !== 0 && difference !== null
			? difference / Math.abs(signed)
			: null;
	const resolved =
		relative !== null &&
		Number.isFinite(relative) &&
		relative <= REFERENCE_NUMERICAL_RELATIVE_TOLERANCE &&
		estimates[0] !== 0 &&
		signed !== null &&
		Math.sign(estimates[0]!) === Math.sign(signed);
	return {
		model: "lowest-foot-sphere-v1",
		signed_stride_m_per_rev: signed,
		owners,
		resolutions: [...RESOLUTIONS],
		samples,
		numerically_resolved: Boolean(resolved),
		resolution_relative_difference:
			relative !== null && Number.isFinite(relative) ? relative : null,
		resolution_relative_tolerance: REFERENCE_NUMERICAL_RELATIVE_TOLERANCE,
	};
}

/** Read the actual builder's sphere ownership; never choose an adjacent bar. */
export function referenceForScenario(sc: SimConfig): StrideReferenceSummary {
	const spec = resolveSpec(sc);
	const key = JSON.stringify({
		walker: sc.walker,
		terrain: sc.terrain,
		spec: {
			params: spec.params,
			crank: spec.crank,
			joints: spec.joints,
			foot: spec.foot,
		},
	});
	const cached = referenceCache.get(key);
	if (cached) return structuredClone(cached);
	const result = computeReference(sc);
	if (referenceCache.size >= 128) {
		const oldest = referenceCache.keys().next().value;
		if (oldest !== undefined) referenceCache.delete(oldest);
	}
	referenceCache.set(key, result);
	return structuredClone(result);
}

function traceConditions(
	sc: SimConfig,
	metrics: Record<string, unknown>,
	series: Record<string, unknown> | null | undefined,
): AuditCondition[] {
	const conditions: AuditCondition[] = [];
	const add = (
		code: string,
		verified: boolean,
		evidence: Record<string, unknown> = {},
	) => {
		conditions.push({
			code,
			status: verified ? "verified" : "unverified",
			evidence,
		});
	};

	const ser =
		series !== null && typeof series === "object" && !Array.isArray(series)
			? series
			: {};

	const array1D = (name: string): number[] | null => {
		const raw = ser[name];
		const valid =
			Array.isArray(raw) &&
			raw.length >= 2 &&
			raw.every((v) => finiteNumber(v));
		if (!valid) {
			add(`finite_${name}`, false, {
				required: "finite, nonempty aligned numeric trace",
			});
			return null;
		}
		return raw as number[];
	};

	const array2D = (name: string): number[][] | null => {
		const raw = ser[name];
		const firstLen =
			Array.isArray(raw) && Array.isArray(raw[0]) ? raw[0].length : -1;
		const valid =
			Array.isArray(raw) &&
			raw.length >= 2 &&
			firstLen >= 0 &&
			raw.every(
				(row) =>
					Array.isArray(row) &&
					row.length === firstLen &&
					row.every((v) => finiteNumber(v)),
			);
		if (!valid) {
			add(`finite_${name}`, false, {
				required: "finite, nonempty aligned numeric trace",
			});
			return null;
		}
		return raw as number[][];
	};

	const t = array1D("t");
	const psi = array1D("psi");
	const x = array1D("x");
	const theta = array1D("theta_rad");
	const normal = array2D("foot_normal");
	const slip = array2D("foot_slip");
	const loopResidual = array1D("loop_residual");
	const penetration = array1D("penetration");

	const allArrays = [t, psi, x, theta, normal, slip, loopResidual, penetration];
	const aligned =
		t !== null && allArrays.every((a) => a !== null && a.length === t.length);
	add("aligned_trace", aligned);

	let everyStep = false;
	if (t !== null) {
		let maxAbsT = sc.solver.timestep;
		for (const v of t) {
			const av = Math.abs(v);
			if (av > maxAbsT) maxAbsT = av;
		}
		const roundoff = 64 * Number.EPSILON * maxAbsT;
		everyStep = sc.run.record_every === 1;
		for (let i = 1; i < t.length && everyStep; i++) {
			const dtStep = t[i]! - t[i - 1]!;
			if (dtStep <= 0 || Math.abs(dtStep - sc.solver.timestep) > roundoff) {
				everyStep = false;
			}
		}
	}
	add("every_integration_step_recorded", everyStep, {
		record_every: sc.run.record_every,
	});
	if (
		!aligned ||
		!t ||
		!psi ||
		!x ||
		!theta ||
		!normal ||
		!slip ||
		!loopResidual ||
		!penetration
	) {
		return conditions;
	}

	const shapes =
		normal[0]?.length === sc.walker.legs && slip[0]?.length === sc.walker.legs;
	add("one_load_and_slip_column_per_leg", shapes);

	if (shapes) {
		const finiteLoads =
			normal.every((row) => row.every((v) => v >= 0)) &&
			slip.every((row) => row.every((v) => v >= 0));
		add("nonnegative_loads_and_slip", finiteLoads);

		const active = normal.map((row) => row.map((f) => f > SUPPORT_FORCE_N));
		const continuousSupport = active.every((row) => row.some(Boolean));
		add("continuous_recorded_support", continuousSupport);

		let anyActive = false;
		let maxLoadedSlip = 0;
		let allZeroLoadedSlip = finiteLoads;
		for (let i = 0; i < active.length; i++) {
			for (let j = 0; j < sc.walker.legs; j++) {
				if (active[i]![j]) {
					anyActive = true;
					const s = slip[i]![j]!;
					if (s !== 0) allZeroLoadedSlip = false;
					if (s > maxLoadedSlip) maxLoadedSlip = s;
				}
			}
		}
		add("zero_recorded_contact_slip", allZeroLoadedSlip, {
			max_loaded_slip_m_s: anyActive ? maxLoadedSlip : null,
		});
	}

	for (const [name, arr, metric] of [
		["loop_residual", loopResidual, "max_loop_violation"],
		["penetration", penetration, "max_penetration"],
	] as const) {
		let maxObs = Number.NEGATIVE_INFINITY;
		let allZero = true;
		for (const v of arr) {
			if (v !== 0) allZero = false;
			if (v > maxObs) maxObs = v;
		}
		add(`zero_recorded_${name}`, allZero && metrics[metric] === 0, {
			max_observed_m: maxObs,
		});
	}

	let maxAbsPhase = 0;
	for (const v of theta)
		if (Math.abs(v) > maxAbsPhase) maxAbsPhase = Math.abs(v);
	for (const v of psi) if (Math.abs(v) > maxAbsPhase) maxAbsPhase = Math.abs(v);
	const phaseRoundoff = 64 * Number.EPSILON * maxAbsPhase;
	let phaseMatches = true;
	for (let i = 1; i < theta.length; i++) {
		const dTheta = theta[i]! - theta[i - 1]!;
		const dPsi = psi[i]! - psi[i - 1]!;
		if (Math.abs(dTheta - sc.walker.direction * dPsi) > phaseRoundoff) {
			phaseMatches = false;
			break;
		}
	}
	add("absolute_phase_matches_progress", phaseMatches);

	if (conditions.every((c) => c.status === "verified")) {
		const spec = resolveSpec(sc);
		let supportsLowest = true;
		for (let i = 0; i < theta.length; i++) {
			const angle = theta[i]!;
			const loaded = normal[i]!.map((f) => f > SUPPORT_FORCE_N);
			const heights: number[] = [];
			let ok = true;
			for (let k = 0; k < sc.walker.legs; k++) {
				const pose = solvePose(
					spec,
					angle + (2 * Math.PI * k) / sc.walker.legs,
				);
				if (!pose || !pose[spec.foot]) {
					ok = false;
					break;
				}
				heights.push(pose[spec.foot]!.y * sc.walker.unit);
			}
			if (!ok) {
				supportsLowest = false;
				break;
			}
			const minH = Math.min(...heights);
			const maxAbsH = Math.max(...heights.map((h) => Math.abs(h)));
			const roundoff = 64 * Number.EPSILON * maxAbsH;
			if (heights.some((h, k) => loaded[k] && h - minH > roundoff)) {
				supportsLowest = false;
				break;
			}
		}
		add("loaded_feet_are_lowest", supportsLowest);
	} else {
		add("loaded_feet_are_lowest", false, {
			reason: "prior_applicability_condition_unverified",
		});
	}

	const tau = 2 * Math.PI;
	const revs = (psi.at(-1)! - psi[0]!) / tau;
	const complete = revs >= 1.98;
	add("complete_gait_window", complete, { recorded_revolutions: revs });
	if (complete) {
		const hi = Math.min(
			tau * (1 + Math.max(1, Math.floor(revs + 0.02) - 1)),
			psi.at(-1)!,
		);
		let i0 = -1;
		let i1 = -1;
		for (let i = 0; i < psi.length; i++) {
			const p = psi[i]!;
			if (p >= tau && p <= hi) {
				if (i0 < 0) i0 = i;
				i1 = i;
			}
		}
		const valid = i0 >= 0 && i1 > i0 && psi[i1]! > psi[i0]!;
		const measured = valid
			? ((x[i1]! - x[i0]!) / (psi[i1]! - psi[i0]!)) * tau
			: null;
		const reported = metrics.stride_per_rev;
		const matches =
			measured !== null &&
			finiteNumber(reported) &&
			Math.abs(measured - reported) <=
				1e-9 * Math.max(Math.abs(measured), Math.abs(reported));
		add("stride_matches_raw_trace", matches, {
			raw_stride_m_per_rev: measured,
		});
	}
	return conditions;
}

/** Return current and unchanged legacy outcomes; unknown is never a pass. */
export function auditReport(
	sc: SimConfig,
	metrics: Record<string, unknown>,
	series: Record<string, unknown> | null | undefined = null,
	stalled = false,
	opts: {
		backendName?: string | null;
		observation?: unknown;
		independentValidation?: unknown;
		independent_validation?: unknown;
	} = {},
): SimulationAuditReport {
	const backendName = opts.backendName ?? null;
	const observation = opts.observation ?? null;
	const legacy = auditLegacy(sc, metrics, series, stalled);
	let findings: AuditFinding[] = structuredClone(
		legacy.filter(
			(f) =>
				f.check !== "stride_vs_kinematics" &&
				f.evidence.metric !== "nominal_stride_m",
		),
	);
	const coverageIssues = observationIssues(
		sc,
		metrics,
		series,
		observation,
		backendName,
	);
	if (coverageIssues.length > 0) {
		findings.push({
			check: "audit_evidence",
			message:
				"Support and peak invariants require complete driven-step observations.",
			evidence: {
				metric: "audit_observation",
				issues: coverageIssues,
			},
		});
	} else {
		findings = findings.filter((f) => f.check !== "support");
		const obs = observation as {
			airborne_steps: number;
			observed_steps: number;
		};
		if (sc.walker.legs >= 4 && metrics.steady_window === 1) {
			const airborne = obs.airborne_steps / obs.observed_steps;
			if (airborne > 0.05) {
				findings.push({
					check: "support",
					message: "The all-step airborne share exceeds the support limit.",
					evidence: {
						airborne_share: airborne,
						limit: 0.05,
						airborne_steps: obs.airborne_steps,
						observed_steps: obs.observed_steps,
					},
				});
			}
		}
	}

	const conditions: AuditCondition[] = [
		{
			code: "native_sphere_model",
			status: backendName === "mujoco" ? "verified" : "unverified",
			evidence: { backend: backendName },
		},
		{
			code: "flat_terrain",
			status: sc.terrain.kind === "flat" ? "verified" : "unverified",
			evidence: { kind: sc.terrain.kind },
		},
		{
			code: "locked_torso_rotation",
			status: sc.walker.pitch === "locked" ? "verified" : "unverified",
			evidence: { pitch: sc.walker.pitch },
		},
		{
			code: "completed_steady_run",
			status:
				!stalled && metrics.steady_window === 1 ? "verified" : "unverified",
			evidence: { stalled: Boolean(stalled) },
		},
		...traceConditions(sc, metrics, series),
	];

	let referenceBase: StrideReferenceSummary;
	try {
		referenceBase = referenceForScenario(sc);
	} catch (exc) {
		referenceBase = {
			model: "lowest-foot-sphere-v1",
			signed_stride_m_per_rev: null,
			numerically_resolved: false,
			error: exc instanceof Error ? exc.message : String(exc),
		};
	}
	conditions.push({
		code: "resolved_signed_reference",
		status: referenceBase.numerically_resolved ? "verified" : "unverified",
		evidence: {},
	});
	const applicable = conditions.every((c) => c.status === "verified");
	const observed = metrics.stride_per_rev;
	const predicted = referenceBase.signed_stride_m_per_rev;
	let relative =
		finiteNumber(observed) && predicted !== null && predicted !== 0
			? Math.abs(observed / predicted - 1)
			: null;
	if (relative !== null && !Number.isFinite(relative)) relative = null;

	const reference = {
		...referenceBase,
		applicability: (applicable ? "verified" : "unverified") as
			| "verified"
			| "unverified",
		conditions,
		comparison: {
			relative_error: relative,
			relative_tolerance: STRIDE_TOLERANCE as typeof STRIDE_TOLERANCE,
			diagnostic_only: !applicable,
		},
	};

	let indepSummary: IndependentValidationSummary | null = null;
	const indepRaw =
		opts.independentValidation ?? opts.independent_validation ?? null;

	if (!applicable) {
		if (indepRaw && typeof indepRaw === "object") {
			const cp = indepRaw as Record<string, unknown>;
			const cpBackend = (cp.backend ?? cp.backend_name ?? null) as
				| string
				| null;
			const cpMetrics = (
				cp.metrics && typeof cp.metrics === "object" ? cp.metrics : cp
			) as Record<string, unknown>;
			const cpStride = (
				finiteNumber(cpMetrics.stride_per_rev)
					? cpMetrics.stride_per_rev
					: finiteNumber(cpMetrics.stride_m_per_rev)
						? cpMetrics.stride_m_per_rev
						: null
			) as number | null;
			const cpStalled = Boolean(cp.stalled ?? cpMetrics.stalled ?? false);
			const cpSteady = cpMetrics.steady_window;
			const cpEnergyRaw =
				cpMetrics.energy_residual_share ?? cpMetrics.energy_residual ?? 0;
			const cpEnergy = finiteNumber(cpEnergyRaw) ? (cpEnergyRaw as number) : 0;
			const cpLoop = finiteNumber(cpMetrics.max_loop_violation)
				? (cpMetrics.max_loop_violation as number)
				: 0;
			const cpPen = finiteNumber(cpMetrics.max_penetration)
				? (cpMetrics.max_penetration as number)
				: 0;
			const cpFindings = Array.isArray(cp.findings)
				? (cp.findings as Array<Record<string, unknown>>)
				: [];
			const cpProvenance = (
				cp.provenance && typeof cp.provenance === "object" ? cp.provenance : {}
			) as Record<string, unknown>;

			if (!cpBackend || cpBackend === backendName) {
				findings.push({
					check: "independent_validation_invalid",
					message:
						"Independent validation requires a distinct simulation backend.",
					evidence: { backend: backendName, counterpart_backend: cpBackend },
				});
				indepSummary = {
					status: "failed",
					backend: cpBackend ?? "",
					stride_m_per_rev: cpStride,
					relative_difference: null,
					relative_tolerance: STRIDE_TOLERANCE,
					provenance: cpProvenance,
				};
			} else if (
				cpStride === null ||
				cpStalled ||
				cpSteady !== 1 ||
				Math.abs(cpEnergy) > ENERGY_RESIDUAL ||
				cpLoop > LOOP_OPEN_M ||
				cpPen > PENETRATION_M ||
				cpFindings.some(
					(f) =>
						f &&
						typeof f.check === "string" &&
						f.check !== "stride_reference_unverified" &&
						f.check !== "audit_evidence",
				)
			) {
				findings.push({
					check: "independent_validation_invalid",
					message:
						"Independent validation counterpart run did not satisfy numerical invariants.",
					evidence: {
						counterpart_backend: cpBackend,
						stride_m_per_rev: cpStride,
						stalled: cpStalled,
						steady_window: cpSteady,
						energy_residual_share: cpEnergy,
						max_loop_violation: cpLoop,
						max_penetration: cpPen,
					},
				});
				indepSummary = {
					status: "failed",
					backend: cpBackend,
					stride_m_per_rev: cpStride,
					relative_difference: null,
					relative_tolerance: STRIDE_TOLERANCE,
					provenance: cpProvenance,
				};
			} else if (!finiteNumber(observed)) {
				findings.push({
					check: "audit_evidence",
					message: "A finite signed stride comparison is required.",
					evidence: { metric: "stride_per_rev" },
				});
			} else {
				let relDiff: number | null =
					Math.abs((observed as number) - cpStride) /
					Math.max(Math.abs(observed as number), 1e-12);
				if (!Number.isFinite(relDiff)) relDiff = null;

				if (relDiff !== null && relDiff <= STRIDE_TOLERANCE) {
					indepSummary = {
						status: "verified",
						backend: cpBackend,
						stride_m_per_rev: cpStride,
						relative_difference: relDiff,
						relative_tolerance: STRIDE_TOLERANCE,
						provenance: cpProvenance,
					};
				} else {
					findings.push({
						check: "stride_vs_independent_validation",
						message:
							"Signed stride differs from the independent dynamical validation run.",
						evidence: {
							stride_m: observed as number,
							independent_stride_m: cpStride,
							relative_error: relDiff,
							limit: STRIDE_TOLERANCE,
						},
					});
					indepSummary = {
						status: "failed",
						backend: cpBackend,
						stride_m_per_rev: cpStride,
						relative_difference: relDiff,
						relative_tolerance: STRIDE_TOLERANCE,
						provenance: cpProvenance,
					};
				}
			}
		} else {
			findings.push({
				check: "stride_reference_unverified",
				message:
					"The geometric reference conditions are not verified; independent dynamics or measurement evidence is required.",
				evidence: {
					unverified_conditions: conditions
						.filter((c) => c.status !== "verified")
						.map((c) => c.code),
					signed_reference_m_per_rev: predicted,
					diagnostic_relative_error: relative,
				},
			});
		}
	} else if (relative === null) {
		findings.push({
			check: "audit_evidence",
			message: "A finite signed stride comparison is required.",
			evidence: { metric: "stride_per_rev" },
		});
	} else if (relative > STRIDE_TOLERANCE) {
		findings.push({
			check: "stride_vs_kinematics",
			message: "Signed stride differs from the applicable geometric reference.",
			evidence: {
				stride_m: observed as number,
				nominal_m: predicted,
				relative_error: relative,
				limit: STRIDE_TOLERANCE,
			},
		});
	}

	if (metrics.steady_window !== 1 || stalled) {
		findings.push({
			check: "audit_evidence",
			message: "A completed steady run is required for the full audit.",
			evidence: { metric: "steady_window", stalled: Boolean(stalled) },
		});
	}

	if (indepSummary) {
		reference.independent_validation = indepSummary;
	}

	const unknown = new Set(["audit_evidence", "stride_reference_unverified"]);
	const status: "passed" | "failed" | "unverified" = findings.some(
		(f) => !unknown.has(f.check),
	)
		? "failed"
		: findings.length > 0
			? "unverified"
			: "passed";

	return {
		version: 2,
		status,
		passed: status === "passed",
		scope: "numerical_invariants_and_applicable_geometric_reference",
		physical_validation_implied: false,
		thresholds: {
			energy_residual: ENERGY_RESIDUAL,
			loop_open_m: LOOP_OPEN_M,
			penetration_m: PENETRATION_M,
			stride_relative: STRIDE_TOLERANCE,
		},
		findings,
		stride_reference: reference,
		...(indepSummary ? { independent_validation: indepSummary } : {}),
		legacy: {
			version: 1,
			passed: legacy.length === 0,
			findings: legacy,
		},
	};
}

/** Version 2 findings: missing applicability is not a successful audit. */
export function audit(
	sc: SimConfig,
	metrics: Record<string, unknown>,
	series: Record<string, unknown> | null | undefined = null,
	stalled = false,
	opts: {
		backendName?: string | null;
		observation?: unknown;
		independentValidation?: unknown;
		independent_validation?: unknown;
	} = {},
): AuditFinding[] {
	return auditReport(sc, metrics, series, stalled, opts).findings;
}
