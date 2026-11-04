import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { auditReport } from "./audit";
import {
	AuditObservation,
	type AuditObservationDocument,
	observationIssues,
} from "./audit-observation";
import { simConfig } from "./config";

const corpus = JSON.parse(
	readFileSync(
		new URL("../../../contracts/sim-observation/cases.json", import.meta.url),
		"utf8",
	),
) as {
	cases: {
		name: string;
		timestep_s: number;
		legs: number;
		boundary: AuditObservationDocument["boundary"];
		integration_steps: number;
		rows: [number, number[], number, number][];
		expected: AuditObservationDocument;
	}[];
};

describe("shared all-step observation contract", () => {
	for (const c of corpus.cases) {
		it(c.name, () => {
			const counter = new AuditObservation(c.timestep_s, c.legs, c.boundary);
			for (const row of c.rows) counter.observe(...row);
			const result = counter.document(c.integration_steps);
			expect(result).toEqual(c.expected);
			result.observed_steps = -100;
			expect(counter.document(c.integration_steps)).toEqual(c.expected);
		});
	}
});

it("retains nonfinite observations as invalid without serializing NaN", () => {
	const counter = new AuditObservation(0.01, 4, "force_evaluation");
	counter.observe(0, [1, 0, 0, 0], Number.NaN, 0);
	const result = counter.document(1);
	expect(result.invalid_steps).toBe(1);
	expect(result.max_loop_residual_m).toBeNull();
	expect(JSON.parse(JSON.stringify(result))).toEqual(result);
});

function supportTrace(airborne: number, recordEvery = 1) {
	const sc = simConfig({
		walker: { legs: 4 },
		solver: { timestep: 0.01 },
		run: { record_every: recordEvery },
	});
	const t = Array.from({ length: 20 }, (_, i) => i * 0.01);
	const normal = Array.from({ length: 20 }, (_, i) =>
		i < airborne ? [0, 0, 0, 0] : [1, 0, 0, 0],
	);
	const collector = new AuditObservation(0.01, 4, "force_evaluation");
	for (let i = 0; i < 20; i++) {
		collector.observe(t[i]!, normal[i]!, 0.005, 0.005);
	}
	const decimate = <T>(arr: T[]) =>
		arr.filter((_, idx) => idx % recordEvery === 0);
	const series = {
		t: decimate(t),
		foot_normal: decimate(normal),
		loop_residual: decimate(new Array<number>(20).fill(0.005)),
		penetration: decimate(new Array<number>(20).fill(0.005)),
	};
	const metrics = {
		steady_window: 1,
		energy_residual_share: 0.02,
		max_loop_violation: 0.005,
		max_penetration: 0.005,
		stride_per_rev: 0.2,
	};
	return { sc, metrics, series, observation: collector.document(20) };
}

describe("observationIssues and all-step support gate", () => {
	for (const recordEvery of [1, 20, 37]) {
		for (const [airborne, failed] of [
			[1, false],
			[2, true],
		] as const) {
			it(`uses all steps at record_every=${recordEvery}, airborne=${airborne}`, () => {
				const { sc, metrics, series, observation } = supportTrace(
					airborne,
					recordEvery,
				);
				expect(
					observationIssues(sc, metrics, series, observation, "mujoco"),
				).toEqual([]);
				const report = auditReport(sc, metrics, series, false, {
					backendName: "mujoco",
					observation,
				});
				const checks = report.findings.map((f) => f.check);
				expect(checks.includes("support")).toBe(failed);
				expect(checks).not.toContain("energy_closure");
				expect(checks).not.toContain("loop_closure");
				expect(checks).not.toContain("penetration");
				expect(report.passed).toBe(false);
				if (recordEvery > 1) {
					expect(report.legacy.findings.map((f) => f.check)).toContain(
						"support",
					);
				}
			});
		}
	}

	it.each([
		["integration_steps", 21],
		["observed_steps", 19],
		["observed_steps", true],
		["invalid_steps", 1],
		["time_gap_steps", 1],
		["airborne_steps", 21],
		["airborne_steps", 0],
		["first_time_s", 0.01],
		["last_time_s", 0.2],
		["last_time_s", Number.NaN],
		["timestep_s", 0.02],
		["legs", 6],
		["boundary", "post_step"],
		["support_force_N", 0.01],
		["max_loop_residual_m", 0.004],
		["max_penetration_m", 0.004],
	] as const)("rejects incomplete or inconsistent %s=%s", (key, value) => {
		const { sc, metrics, series, observation } = supportTrace(1);
		(observation as unknown as Record<string, unknown>)[key] = value;
		expect(
			observationIssues(sc, metrics, series, observation, "mujoco").length,
		).toBeGreaterThan(0);
		const report = auditReport(sc, metrics, series, false, {
			backendName: "mujoco",
			observation,
		});
		expect(report.passed).toBe(false);
		expect(
			report.findings.some(
				(f) =>
					f.check === "audit_evidence" &&
					f.evidence.metric === "audit_observation",
			),
		).toBe(true);
	});

	it("preserves historical sampled support failure when observation is missing", () => {
		const { sc, metrics, series } = supportTrace(1, 20);
		const report = auditReport(sc, metrics, series, false, {
			backendName: "mujoco",
		});
		expect(report.status).toBe("failed");
		expect(report.findings.map((f) => f.check)).toContain("support");
	});

	it("rejects forged peak that hides a violation in raw samples", () => {
		const { sc, metrics, series, observation } = supportTrace(1);
		series.penetration[3] = 0.006;
		expect(observationIssues(sc, metrics, series, observation)).toContain(
			"recorded_max_penetration_m_disagrees",
		);
	});
});
