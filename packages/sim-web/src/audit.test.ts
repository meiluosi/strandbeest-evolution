/** ADR-0012: a computable geometric estimate is not evidence of applicability (sim-web port). */
import { readFileSync } from "node:fs";
import {
	createWasmKinematicsKernel,
	type Design,
	installKinematicsKernel,
	referenceKinematicsKernel,
	solvePose,
} from "strandbeest-core";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import * as bindings from "../../../crates/beest-kernel/generated/beest_kernel.js";
import { audit, auditLegacy, auditReport, referenceForScenario } from "./audit";
import { AuditObservation } from "./audit-observation";
import { resolveSpec } from "./builder";
import { scenarioFromDesign } from "./from-design";

const repo = (p: string) => new URL(`../../../${p}`, import.meta.url);
const baseDesign = JSON.parse(
	readFileSync(repo("schemas/examples/design-jansen-small-6leg.json"), "utf8"),
) as Design;

beforeAll(() => {
	bindings.initSync({
		module: readFileSync(
			repo("crates/beest-kernel/generated/beest_kernel_bg.wasm"),
		),
	});
	installKinematicsKernel(createWasmKinematicsKernel(bindings));
});

afterAll(() => {
	installKinematicsKernel(referenceKinematicsKernel);
});

function makeControlled() {
	const sc = scenarioFromDesign(baseDesign, {
		solver: { timestep: 0.01 },
		run: { record_every: 1 },
	});
	const nominal = referenceForScenario(sc).signed_stride_m_per_rev as number;
	const n = 701;
	const t = Array.from({ length: n }, (_, i) => i * 0.01);
	const psi = t.map((v) => 2 * v);
	const theta = psi.map((v) => sc.walker.direction * v);
	const x = psi.map((v) => (nominal * v) / (2 * Math.PI));
	const spec = resolveSpec(sc);
	const normal = Array.from({ length: n }, (_, i) => {
		const angle = theta[i]!;
		let bestLeg = 0;
		let minHeight = Number.POSITIVE_INFINITY;
		for (let k = 0; k < sc.walker.legs; k++) {
			const pose = solvePose(spec, angle + (2 * Math.PI * k) / sc.walker.legs)!;
			const h = pose[spec.foot]!.y;
			if (h < minHeight) {
				minHeight = h;
				bestLeg = k;
			}
		}
		const row = new Array<number>(sc.walker.legs).fill(0);
		row[bestLeg] = 1;
		return row;
	});
	const footSlip = Array.from({ length: n }, () =>
		new Array<number>(sc.walker.legs).fill(0),
	);
	const loopResidual = new Array<number>(n).fill(0);
	const penetration = new Array<number>(n).fill(0);
	const series: Record<string, unknown> = {
		t,
		psi,
		theta_rad: theta,
		x,
		foot_normal: normal,
		foot_slip: footSlip,
		loop_residual: loopResidual,
		penetration,
	};
	const metrics: Record<string, unknown> = {
		steady_window: 1,
		energy_residual_share: 0,
		max_loop_violation: 0,
		max_penetration: 0,
		stride_per_rev: nominal,
	};
	const obs = new AuditObservation(
		sc.solver.timestep,
		sc.walker.legs,
		"force_evaluation",
	);
	for (let i = 0; i < n; i++) {
		obs.observe(t[i]!, normal[i]!, 0, 0);
	}
	return { sc, metrics, series, observation: obs.document(n) };
}

function runReport(c = makeControlled()) {
	return auditReport(c.sc, c.metrics, c.series, false, {
		backendName: "mujoco",
		observation: c.observation,
	});
}

describe("sim-web v2 audit policy (ADR-0012)", () => {
	it("gives a scoped pass and legacy record for a controlled exact-constraint trace", () => {
		const value = runReport();
		expect(value.version).toBe(2);
		expect(value.status).toBe("passed");
		expect(value.passed).toBe(true);
		expect(value.findings).toEqual([]);
		expect(value.legacy.version).toBe(1);
		expect(value.physical_validation_implied).toBe(false);
		expect(value.stride_reference.applicability).toBe("verified");
	});

	it.each([
		"foot_normal",
		"foot_slip",
		"loop_residual",
		"penetration",
		"t",
		"psi",
		"x",
		"theta_rad",
	] as const)("missing applicability input %s cannot be a pass", (key) => {
		const c = makeControlled();
		delete c.series[key];
		const value = runReport(c);
		expect(value.passed).toBe(false);
		expect(value.status).toBe("unverified");
		expect(
			value.findings.some(
				(f) =>
					f.check === "stride_reference_unverified" ||
					f.check === "audit_evidence",
			),
		).toBe(true);
	});

	it.each([
		["foot_slip", 1e-12],
		["loop_residual", 1e-12],
		["penetration", 1e-12],
	] as const)(
		"nonzero physical deviation %s=%d is not hidden in a numerical tolerance",
		(key, val) => {
			const c = makeControlled();
			if (key === "foot_slip") {
				(c.series.foot_slip as number[][])[10] = new Array<number>(
					c.sc.walker.legs,
				).fill(val);
			} else {
				(c.series[key] as number[])[10] = val;
			}
			expect(runReport(c).status).toBe("unverified");
		},
	);

	it("flight and decimated telemetry do not certify lowest-foot support", () => {
		const c = makeControlled();
		(c.series.foot_normal as number[][])[20] = new Array<number>(
			c.sc.walker.legs,
		).fill(0);
		expect(runReport(c).status).toBe("unverified");

		const c2 = makeControlled();
		c2.sc.run.record_every = 20;
		expect(runReport(c2).status).toBe("unverified");
	});

	it.each(["slope", "pitch", "stalled", "unknown_backend"] as const)(
		"outside reference scope (%s) requires independent validation",
		(change) => {
			const c = makeControlled();
			if (change === "slope") c.sc.terrain.kind = "slope";
			if (change === "pitch") c.sc.walker.pitch = "free";
			const value = auditReport(
				c.sc,
				c.metrics,
				c.series,
				change === "stalled",
				{
					backendName: change === "unknown_backend" ? null : "mujoco",
					observation: c.observation,
				},
			);
			expect(value.status).toBe("unverified");
			expect(value.passed).toBe(false);
		},
	);

	it("preserves sign and fails opposite motion without absolute-value rescue", () => {
		const c = makeControlled();
		c.sc.walker.direction = -c.sc.walker.direction as -1 | 1;
		const theta = (c.series.theta_rad as number[]).map((v) => -v);
		c.series.theta_rad = theta;
		const spec = resolveSpec(c.sc);
		const normal = c.series.foot_normal as number[][];
		for (let i = 0; i < theta.length; i++) {
			const angle = theta[i]!;
			let bestLeg = 0;
			let minHeight = Number.POSITIVE_INFINITY;
			for (let k = 0; k < c.sc.walker.legs; k++) {
				const pose = solvePose(
					spec,
					angle + (2 * Math.PI * k) / c.sc.walker.legs,
				)!;
				const h = pose[spec.foot]!.y;
				if (h < minHeight) {
					minHeight = h;
					bestLeg = k;
				}
			}
			const row = new Array<number>(c.sc.walker.legs).fill(0);
			row[bestLeg] = 1;
			normal[i] = row;
		}
		const expected = referenceForScenario(c.sc)
			.signed_stride_m_per_rev as number;
		expect(expected).toBeCloseTo(-(c.metrics.stride_per_rev as number), 12);
		expect(runReport(c).status).toBe("failed");

		c.metrics.stride_per_rev = expected;
		c.series.x = (c.series.x as number[]).map((v) => -v);
		expect(runReport(c).status).toBe("passed");
	});

	it("rejects incompatible elevated supports even when slip is zero", () => {
		const c = makeControlled();
		c.series.foot_normal = (c.series.foot_normal as number[][]).map(() =>
			new Array<number>(c.sc.walker.legs).fill(1),
		);
		const value = runReport(c);
		expect(value.status).toBe("unverified");
		expect(
			value.stride_reference.conditions.some(
				(cond) =>
					cond.code === "loaded_feet_are_lowest" &&
					cond.status === "unverified",
			),
		).toBe(true);
	});

	it("reference cache does not share mutable outputs", () => {
		const c = makeControlled();
		const initial = referenceForScenario(c.sc);
		initial.signed_stride_m_per_rev = 99;
		expect(referenceForScenario(c.sc).signed_stride_m_per_rev).not.toBe(99);
	});

	it.each([
		["energy_residual_share", 0.021, "energy_closure"],
		["max_loop_violation", 0.0051, "loop_closure"],
		["max_penetration", 0.0051, "penetration"],
	] as const)(
		"original numeric threshold %s=%f still fails even when stride is unverified",
		(key, val, code) => {
			const c = makeControlled();
			c.metrics[key] = val;
			c.sc.run.record_every = 20;
			const value = runReport(c);
			expect(value.status).toBe("failed");
			expect(value.findings.map((f) => f.check)).toContain(code);
		},
	);

	it("preserves legacy result and is read-only and JSON-serializable", () => {
		const c = makeControlled();
		c.sc.run.record_every = 20;
		const before = structuredClone(c);
		const value = runReport(c);
		expect(value.legacy.findings).toEqual(
			auditLegacy(c.sc, c.metrics, c.series),
		);
		expect(
			audit(c.sc, c.metrics, c.series, false, { backendName: "mujoco" }).length,
		).toBeGreaterThan(0);
		expect(JSON.parse(JSON.stringify(value))).toEqual(value);
		expect(c).toEqual(before);
	});
});
