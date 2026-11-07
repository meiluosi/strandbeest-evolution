import { jansenSpec, trace } from "strandbeest-core";

export interface Point2D {
	x: number;
	z: number;
}

export interface PhasePoint {
	theta: number;
	dx: number;
	dx_sigma_lo: number;
	dx_sigma_hi: number;
	dx_ci95_lo: number;
	dx_ci95_hi: number;
}

export interface VelocityPoint {
	t: number;
	v_meas: number;
	v_sim: number;
	v_kin: number;
}

export interface StrideMetrics {
	stride_m: number;
	uncertainty_m: number;
	ci95_lo_m: number;
	ci95_hi_m: number;
	sigma_lo_m: number;
	sigma_hi_m: number;
	rel_diff_sim_pct: number;
	rel_diff_kin_pct: number;
	within_envelope: boolean;
}

export interface VideoTwinBenchmark {
	nominal: {
		theoretical_stride_m: number;
		simulated_stride_m: number;
		measured_stride_m: number;
		measured_sigma_m: number;
		ci95_lo_m: number;
		ci95_hi_m: number;
		sigma_lo_m: number;
		sigma_hi_m: number;
		rel_diff_sim_pct: number;
		rel_diff_kin_pct: number;
		scale_uncertainty_pct: number;
		within_envelope: boolean;
		duration_s: number;
		dx_m: number;
		v_mean_m_s: number;
		f_crank_hz: number;
		crank_period_s: number;
		omega_rad_s: number;
		revolutions: number;
	};
	provenance: {
		video_title: string;
		author: string;
		license: string;
		date: string;
		sha256: string;
		evidence_level: "E0" | "E1" | "E2" | "E3";
		calibrated_mpp: number;
		scale_uncertainty_mpp: number;
	};
	literature: {
		source: string;
		measured_m: number;
		simulated_m: number;
		prototype_error_pct: number;
	};
	foot_trajectories: {
		theoretical: Point2D[];
		simulated: Point2D[];
		measured: Point2D[];
		measured_ci95_upper: Point2D[];
		measured_ci95_lower: Point2D[];
	};
	phase_curves: {
		theoretical: { theta: number; dx: number }[];
		simulated: { theta: number; dx: number }[];
		measured: PhasePoint[];
	};
	velocity_series: VelocityPoint[];
}

export const THEORETICAL_STRIDE_M = 2.8747;
export const SIMULATED_STRIDE_M = 2.921;
export const MEASURED_STRIDE_M = 2.80082;
export const CALIBRATED_MPP = 0.003895;
export const SCALE_UNCERTAINTY_MPP = 0.00021; // +/- 5.39% (~5.4%)
export const SCALE_UNCERTAINTY_PCT = 5.39;
export const FULLSCALE_UNIT_M = 0.02052;

export function computeStrideMetrics(
	measuredStride: number,
	scaleUncertaintyPct = SCALE_UNCERTAINTY_PCT,
): StrideMetrics {
	const sigma = (measuredStride * scaleUncertaintyPct) / 100.0;
	const ci95Half = 1.96 * sigma;

	const ci95_lo_m = measuredStride - ci95Half;
	const ci95_hi_m = measuredStride + ci95Half;
	const sigma_lo_m = measuredStride - sigma;
	const sigma_hi_m = measuredStride + sigma;

	const diff_sim = measuredStride - SIMULATED_STRIDE_M;
	const rel_diff_sim_pct = (diff_sim / SIMULATED_STRIDE_M) * 100.0;

	const diff_kin = measuredStride - THEORETICAL_STRIDE_M;
	const rel_diff_kin_pct = (diff_kin / THEORETICAL_STRIDE_M) * 100.0;

	const within_envelope =
		Math.abs(diff_sim) <= ci95Half && Math.abs(diff_kin) <= ci95Half;

	return {
		stride_m: Number(measuredStride.toFixed(4)),
		uncertainty_m: Number(sigma.toFixed(4)),
		ci95_lo_m: Number(ci95_lo_m.toFixed(4)),
		ci95_hi_m: Number(ci95_hi_m.toFixed(4)),
		sigma_lo_m: Number(sigma_lo_m.toFixed(4)),
		sigma_hi_m: Number(sigma_hi_m.toFixed(4)),
		rel_diff_sim_pct: Number(rel_diff_sim_pct.toFixed(2)),
		rel_diff_kin_pct: Number(rel_diff_kin_pct.toFixed(2)),
		within_envelope,
	};
}

export function computeFootTrajectoryKinematic(samples = 100): Point2D[] {
	const spec = jansenSpec();
	const t = trace(spec, samples);
	if (!t.assembled || t.foot.length === 0) {
		return [];
	}
	return t.foot.map((p) => ({
		x: Number((p.x * FULLSCALE_UNIT_M).toFixed(4)),
		z: Number((p.y * FULLSCALE_UNIT_M).toFixed(4)),
	}));
}

export function computeFootTrajectorySimulated(samples = 100): Point2D[] {
	// Kinematic closed-form trajectory scaled by simulated stride ratio
	const kin = computeFootTrajectoryKinematic(samples);
	const dynamicStretchX = SIMULATED_STRIDE_M / THEORETICAL_STRIDE_M;
	return kin.map((p) => ({
		x: Number((p.x * dynamicStretchX).toFixed(4)),
		z: Number(p.z.toFixed(4)),
	}));
}

export function computeFootTrajectoryMeasured(samples = 100): {
	measured: Point2D[];
	ci95_upper: Point2D[];
	ci95_lower: Point2D[];
} {
	// Video tracking measured chassis x(t); foot points are an illustrative overlay based on kinematic geometry scaled by measured stride
	const kin = computeFootTrajectoryKinematic(samples);
	const minZ = Math.min(...kin.map((p) => p.z));

	const measured: Point2D[] = [];
	const ci95_upper: Point2D[] = [];
	const ci95_lower: Point2D[] = [];

	const shrinkFactor = MEASURED_STRIDE_M / THEORETICAL_STRIDE_M; // ~0.9743 (-2.57%)
	const scaleErr = (SCALE_UNCERTAINTY_PCT / 100.0) * 1.96; // ~10.56% at 95% CI

	for (let i = 0; i < kin.length; i++) {
		const p = kin[i] as Point2D;
		const isStance = p.z <= minZ + 0.05;
		const mx = p.x * shrinkFactor;
		const mz = p.z + (isStance ? 0.006 : 0.0);

		measured.push({
			x: Number(mx.toFixed(4)),
			z: Number(mz.toFixed(4)),
		});

		// 95% Confidence uncertainty envelope boundaries from scale calibration
		ci95_upper.push({
			x: Number((mx * (1 + scaleErr)).toFixed(4)),
			z: Number((mz + 0.025).toFixed(4)),
		});
		ci95_lower.push({
			x: Number((mx * (1 - scaleErr)).toFixed(4)),
			z: Number((mz - 0.025).toFixed(4)),
		});
	}

	return { measured, ci95_upper, ci95_lower };
}

export function computePhaseCurves(steps = 60): {
	theoretical: { theta: number; dx: number }[];
	simulated: { theta: number; dx: number }[];
	measured: PhasePoint[];
} {
	const theoretical: { theta: number; dx: number }[] = [];
	const simulated: { theta: number; dx: number }[] = [];
	const measured: PhasePoint[] = [];

	const sigmaRate = SCALE_UNCERTAINTY_PCT / 100.0;
	const ci95Rate = 1.96 * sigmaRate;

	for (let i = 0; i <= steps; i++) {
		const frac = i / steps;
		const theta = Number((frac * 2.0 * Math.PI).toFixed(4));
		const dxKin = THEORETICAL_STRIDE_M * frac;
		const dxSim = SIMULATED_STRIDE_M * frac;
		const dxMeas = MEASURED_STRIDE_M * frac;

		const sigmaSpan = dxMeas * sigmaRate;
		const ci95Span = dxMeas * ci95Rate;

		theoretical.push({
			theta,
			dx: Number(dxKin.toFixed(4)),
		});
		simulated.push({
			theta,
			dx: Number(dxSim.toFixed(4)),
		});
		measured.push({
			theta,
			dx: Number(dxMeas.toFixed(4)),
			dx_sigma_lo: Number((dxMeas - sigmaSpan).toFixed(4)),
			dx_sigma_hi: Number((dxMeas + sigmaSpan).toFixed(4)),
			dx_ci95_lo: Number((dxMeas - ci95Span).toFixed(4)),
			dx_ci95_hi: Number((dxMeas + ci95Span).toFixed(4)),
		});
	}

	return { theoretical, simulated, measured };
}

export function computeVelocitySeries(points = 50): VelocityPoint[] {
	const totalT = 9.97;
	const vMeanMeas = 0.126;
	const vMeanSim = (vMeanMeas * SIMULATED_STRIDE_M) / MEASURED_STRIDE_M;
	const vMeanKin = (vMeanMeas * THEORETICAL_STRIDE_M) / MEASURED_STRIDE_M;

	const out: VelocityPoint[] = [];
	for (let i = 0; i < points; i++) {
		const t = Number(((i / (points - 1)) * totalT).toFixed(3));
		const v_meas = Number(vMeanMeas.toFixed(4));
		const v_sim = Number(vMeanSim.toFixed(4));
		const v_kin = Number(vMeanKin.toFixed(4));
		out.push({ t, v_meas, v_sim, v_kin });
	}
	return out;
}

export function getBinnenhofBenchmark(): VideoTwinBenchmark {
	const metrics = computeStrideMetrics(MEASURED_STRIDE_M);
	const footCurves = computeFootTrajectoryMeasured(100);
	const phaseCurves = computePhaseCurves(60);
	const velocitySeries = computeVelocitySeries(50);

	return {
		nominal: {
			theoretical_stride_m: THEORETICAL_STRIDE_M,
			simulated_stride_m: SIMULATED_STRIDE_M,
			measured_stride_m: metrics.stride_m,
			measured_sigma_m: metrics.uncertainty_m,
			ci95_lo_m: metrics.ci95_lo_m,
			ci95_hi_m: metrics.ci95_hi_m,
			sigma_lo_m: metrics.sigma_lo_m,
			sigma_hi_m: metrics.sigma_hi_m,
			rel_diff_sim_pct: metrics.rel_diff_sim_pct,
			rel_diff_kin_pct: metrics.rel_diff_kin_pct,
			scale_uncertainty_pct: SCALE_UNCERTAINTY_PCT,
			within_envelope: metrics.within_envelope,
			duration_s: 9.97,
			dx_m: 1.2562,
			v_mean_m_s: 0.126,
			f_crank_hz: 0.045,
			crank_period_s: 22.22,
			omega_rad_s: 0.2827,
			revolutions: 0.4485,
		},
		provenance: {
			video_title:
				"Het Strandbeest van kunstenaar Theo Jansen loopt over het Binnenhof",
			author: "Tweede Kamer der Staten-Generaal",
			license: "CC BY 3.0",
			date: "2016-04-13",
			sha256:
				"9944c693e7326d19c839b208790230fea1b03532eed189cedcd72cc76772e478",
			evidence_level: "E0",
			calibrated_mpp: CALIBRATED_MPP,
			scale_uncertainty_mpp: SCALE_UNCERTAINTY_MPP,
		},
		literature: {
			source: "Nansai et al. 2015, DOI: 10.1177/1687814015573824",
			measured_m: 0.3342,
			simulated_m: 0.3982,
			prototype_error_pct: 16.07,
		},
		foot_trajectories: {
			theoretical: computeFootTrajectoryKinematic(100),
			simulated: computeFootTrajectorySimulated(100),
			measured: footCurves.measured,
			measured_ci95_upper: footCurves.ci95_upper,
			measured_ci95_lower: footCurves.ci95_lower,
		},
		phase_curves: {
			theoretical: phaseCurves.theoretical,
			simulated: phaseCurves.simulated,
			measured: phaseCurves.measured,
		},
		velocity_series: velocitySeries,
	};
}

export interface ParsedMeasurement {
	name: string;
	stride_m: number;
	duration_s: number;
	dx_m: number;
	v_mean_m_s: number;
	revolutions: number;
	metrics: StrideMetrics;
	channels: {
		t: number[];
		x: number[];
		psi?: number[];
	};
}

export function parseMeasurementData(
	content: string,
	fileName = "custom-measurement",
): ParsedMeasurement {
	const trimmed = content.trim();
	if (!trimmed) {
		throw new Error("File content is empty");
	}

	if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
		const doc = JSON.parse(trimmed);
		const ch = doc.channels ?? doc;
		if (!ch.t || !Array.isArray(ch.t) || ch.t.length < 2) {
			throw new Error("Missing required channels: t array of length >= 2");
		}
		if (!ch.x || !Array.isArray(ch.x) || ch.x.length !== ch.t.length) {
			throw new Error("Missing required channels: x array matching t length");
		}

		const t = ch.t.map(Number);
		const x = ch.x.map(Number);
		const psi = Array.isArray(ch.psi) ? ch.psi.map(Number) : undefined;

		const dt = Math.max(0.001, t[t.length - 1] - t[0]);
		const dx = Math.abs(x[x.length - 1] - x[0]);
		const vMean = dx / dt;

		let revs = 1.0;
		if (psi && psi.length === t.length) {
			const dPsi = Math.abs(psi[psi.length - 1] - psi[0]);
			if (dPsi > 0.01) {
				revs = dPsi / (2.0 * Math.PI);
			}
		} else if (doc.conditions?.omega_rad_s) {
			const omega = Number(doc.conditions.omega_rad_s);
			revs = Math.max(0.01, (omega * dt) / (2.0 * Math.PI));
		}

		const stride_m = dx / revs;
		const metrics = computeStrideMetrics(stride_m);

		return {
			name: doc.name ?? doc.id ?? fileName,
			stride_m: Number(stride_m.toFixed(4)),
			duration_s: Number(dt.toFixed(3)),
			dx_m: Number(dx.toFixed(4)),
			v_mean_m_s: Number(vMean.toFixed(4)),
			revolutions: Number(revs.toFixed(3)),
			metrics,
			channels: { t, x, psi },
		};
	}

	// CSV parsing
	const lines = trimmed.split(/\r?\n/).filter((l) => l.trim().length > 0);
	if (lines.length < 2) {
		throw new Error("CSV file must have header and at least one data row");
	}

	const firstLine = lines[0];
	if (!firstLine) {
		throw new Error("CSV file must have header and at least one data row");
	}

	const headers = firstLine.split(",").map((h) => h.trim().toLowerCase());
	const tIdx = headers.indexOf("t");
	const xIdx = headers.indexOf("x");
	const psiIdx = headers.indexOf("psi");

	if (tIdx === -1 || xIdx === -1) {
		throw new Error("CSV header must contain 't' and 'x' columns");
	}

	const t: number[] = [];
	const x: number[] = [];
	const psi: number[] = [];

	for (let i = 1; i < lines.length; i++) {
		const line = lines[i];
		if (!line) continue;
		const row = line.split(",").map((v) => Number(v.trim()));
		if (row.length <= Math.max(tIdx, xIdx)) continue;
		const tVal = row[tIdx];
		const xVal = row[xIdx];
		if (tVal === undefined || xVal === undefined) continue;
		t.push(tVal);
		x.push(xVal);
		if (psiIdx !== -1) {
			const psiVal = row[psiIdx];
			if (psiVal !== undefined) {
				psi.push(psiVal);
			}
		}
	}

	if (t.length < 2) {
		throw new Error("CSV requires at least 2 valid numeric rows");
	}

	const tLast = t[t.length - 1] ?? 0;
	const tFirst = t[0] ?? 0;
	const xLast = x[x.length - 1] ?? 0;
	const xFirst = x[0] ?? 0;
	const dt = Math.max(0.001, tLast - tFirst);
	const dx = Math.abs(xLast - xFirst);
	const vMean = dx / dt;

	let revs = 1.0;
	if (psi.length === t.length && psi.length > 0) {
		const psiLast = psi[psi.length - 1] ?? 0;
		const psiFirst = psi[0] ?? 0;
		const dPsi = Math.abs(psiLast - psiFirst);
		if (dPsi > 0.01) {
			revs = dPsi / (2.0 * Math.PI);
		}
	}

	const stride_m = dx / revs;
	const metrics = computeStrideMetrics(stride_m);

	return {
		name: fileName,
		stride_m: Number(stride_m.toFixed(4)),
		duration_s: Number(dt.toFixed(3)),
		dx_m: Number(dx.toFixed(4)),
		v_mean_m_s: Number(vMean.toFixed(4)),
		revolutions: Number(revs.toFixed(3)),
		metrics,
		channels: { t, x, psi: psi.length > 0 ? psi : undefined },
	};
}
