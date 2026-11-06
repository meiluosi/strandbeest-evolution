import { describe, expect, it } from "vitest";
import {
	CALIBRATED_MPP,
	computeFootTrajectoryKinematic,
	computeFootTrajectoryMeasured,
	computeFootTrajectorySimulated,
	computePhaseCurves,
	computeStrideMetrics,
	computeVelocitySeries,
	getBinnenhofBenchmark,
	MEASURED_STRIDE_M,
	parseMeasurementData,
	SCALE_UNCERTAINTY_MPP,
	SCALE_UNCERTAINTY_PCT,
	SIMULATED_STRIDE_M,
	THEORETICAL_STRIDE_M,
} from "./video-twin";

describe("video-twin metrics and benchmark", () => {
	it("matches nominal benchmark strides and uncertainty limits", () => {
		expect(THEORETICAL_STRIDE_M).toBeCloseTo(2.875, 2);
		expect(SIMULATED_STRIDE_M).toBeCloseTo(2.921, 2);
		expect(MEASURED_STRIDE_M).toBeCloseTo(2.801, 2);

		// Calibrated pixel scale and uncertainty
		expect(CALIBRATED_MPP).toBe(0.003895);
		expect(SCALE_UNCERTAINTY_MPP).toBe(0.00021);
		expect(SCALE_UNCERTAINTY_PCT).toBeCloseTo(5.39, 1);
	});

	it("computes stride metrics and verifies the error envelope", () => {
		const metrics = computeStrideMetrics(MEASURED_STRIDE_M);

		expect(metrics.stride_m).toBe(2.8008);
		expect(metrics.uncertainty_m).toBeCloseTo(0.151, 3);

		// 95% Confidence Interval: [2.505, 3.097] m/rev
		expect(metrics.ci95_lo_m).toBeCloseTo(2.505, 2);
		expect(metrics.ci95_hi_m).toBeCloseTo(3.097, 2);

		// 1-sigma uncertainty: [2.650, 2.952] m/rev
		expect(metrics.sigma_lo_m).toBeCloseTo(2.65, 2);
		expect(metrics.sigma_hi_m).toBeCloseTo(2.952, 2);

		// Percentage deviations: -4.11% vs simulation, -2.57% vs kinematics
		expect(metrics.rel_diff_sim_pct).toBeCloseTo(-4.11, 2);
		expect(metrics.rel_diff_kin_pct).toBeCloseTo(-2.57, 2);

		// Must fall strictly within the +/- 5.4% optical scale uncertainty envelope!
		expect(metrics.within_envelope).toBe(true);
		expect(Math.abs(metrics.rel_diff_sim_pct)).toBeLessThan(
			SCALE_UNCERTAINTY_PCT,
		);
		expect(Math.abs(metrics.rel_diff_kin_pct)).toBeLessThan(
			SCALE_UNCERTAINTY_PCT,
		);
	});

	it("provides complete Binnenhof provenance and literature citation", () => {
		const bench = getBinnenhofBenchmark();

		// Video provenance
		expect(bench.provenance.license).toBe("CC BY 3.0");
		expect(bench.provenance.author).toBe("Tweede Kamer der Staten-Generaal");
		expect(bench.provenance.evidence_level).toBe("E2");
		expect(bench.provenance.sha256).toBe(
			"9944c693e7326d19c839b208790230fea1b03532eed189cedcd72cc76772e478",
		);

		// Literature marker: Nansai et al. 2015
		expect(bench.literature.source).toContain("Nansai et al. 2015");
		expect(bench.literature.prototype_error_pct).toBe(16.07);
		expect(bench.literature.measured_m).toBe(0.3342);
		expect(bench.literature.simulated_m).toBe(0.3982);
	});

	it("generates closed foot trajectories for 3 comparison paths", () => {
		const kin = computeFootTrajectoryKinematic(60);
		const sim = computeFootTrajectorySimulated(60);
		const meas = computeFootTrajectoryMeasured(60);

		expect(kin.length).toBe(60);
		expect(sim.length).toBe(60);
		expect(meas.measured.length).toBe(60);
		expect(meas.ci95_upper.length).toBe(60);
		expect(meas.ci95_lower.length).toBe(60);

		// Check coordinates are in reasonable meter scale for full-scale walker
		const minKinZ = Math.min(...kin.map((p) => p.z));
		const maxKinZ = Math.max(...kin.map((p) => p.z));
		expect(minKinZ).toBeLessThan(-1.5);
		expect(maxKinZ).toBeGreaterThan(-1.4);

		// Simulated foot shows compliance sag during stance
		const minSimZ = Math.min(...sim.map((p) => p.z));
		expect(minSimZ).toBeLessThan(minKinZ);
	});

	it("computes crank phase displacement and velocity curves", () => {
		const { theoretical, simulated, measured } = computePhaseCurves(40);
		expect(theoretical.length).toBe(41);
		expect(simulated.length).toBe(41);
		expect(measured.length).toBe(41);

		// At theta = 2*pi, displacement reaches full stride
		const lastKin = theoretical[theoretical.length - 1]!;
		const lastSim = simulated[simulated.length - 1]!;
		const lastMeas = measured[measured.length - 1]!;

		expect(lastKin.dx).toBeCloseTo(THEORETICAL_STRIDE_M, 1);
		expect(lastSim.dx).toBeCloseTo(SIMULATED_STRIDE_M, 1);
		expect(lastMeas.dx).toBeCloseTo(MEASURED_STRIDE_M, 1);
		expect(lastMeas.dx_ci95_lo).toBeLessThan(lastMeas.dx);
		expect(lastMeas.dx_ci95_hi).toBeGreaterThan(lastMeas.dx);

		const velocities = computeVelocitySeries(30);
		expect(velocities.length).toBe(30);
		expect(velocities[0]!.v_meas).toBeGreaterThan(0.1);
	});

	it("parses valid JSON measurement asset", () => {
		const sampleJson = JSON.stringify({
			schema_version: 2,
			name: "test-walk",
			conditions: { omega_rad_s: 0.2827 },
			channels: {
				t: [0.0, 1.0, 2.0, 3.0, 4.0],
				x: [0.0, 0.126, 0.252, 0.378, 0.504],
				psi: [0.0, 0.2827, 0.5654, 0.8481, 1.1308],
			},
		});

		const res = parseMeasurementData(sampleJson, "test.json");
		expect(res.name).toBe("test-walk");
		expect(res.dx_m).toBe(0.504);
		expect(res.duration_s).toBe(4.0);
		expect(res.v_mean_m_s).toBeCloseTo(0.126, 3);
		expect(res.stride_m).toBeCloseTo(2.8, 1);
		expect(res.metrics.within_envelope).toBe(true);
	});

	it("parses valid CSV measurement data", () => {
		const sampleCsv = `t,x,psi\n0.0,0.0,0.0\n1.0,0.14,0.314\n2.0,0.28,0.628`;
		const res = parseMeasurementData(sampleCsv, "run.csv");
		expect(res.name).toBe("run.csv");
		expect(res.dx_m).toBe(0.28);
		expect(res.duration_s).toBe(2.0);
		expect(res.stride_m).toBeCloseTo(2.8, 1);
	});

	it("rejects invalid measurement formats", () => {
		expect(() => parseMeasurementData("")).toThrow("empty");
		expect(() => parseMeasurementData("invalid csv without headers")).toThrow(
			"header",
		);
		expect(() => parseMeasurementData(JSON.stringify({}))).toThrow(
			"Missing required channels",
		);
	});
});
