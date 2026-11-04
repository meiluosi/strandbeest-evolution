/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import fitnessCorpus from "../../../contracts/fitness/cases.json";
import boundaryCorpus from "../../../contracts/kernel-boundaries.json";
import * as bindings from "../../../crates/beest-kernel/generated/beest_kernel.js";
import { fitnessFlatStroke, fitnessHighStep, infeasibility } from "./fitness";
import { genomeSpace } from "./genome";
import {
	createWasmKinematicsKernel,
	installKinematicsKernel,
	kinematicsKernel,
	referenceKinematicsKernel,
} from "./kernel";
import { type LinkageSpec, solvePose, trace } from "./linkage";
import { gaitMetrics } from "./metrics";

const root = new URL("../../../", import.meta.url);
let wasm: ReturnType<typeof createWasmKinematicsKernel>;
let memory: WebAssembly.Memory;
beforeAll(() => {
	memory = bindings.initSync({
		module: readFileSync(
			new URL("crates/beest-kernel/generated/beest_kernel_bg.wasm", root),
		),
	}).memory;
	wasm = createWasmKinematicsKernel(bindings);
});
afterEach(() => installKinematicsKernel(referenceKinematicsKernel));

describe("real Rust/WASM kernel, through the public core API", () => {
	for (const file of readdirSync(new URL("contracts/kinematics/", root)).filter(
		(f) => f.endsWith(".json"),
	)) {
		it(`${file}: every recorded pose, full path, branch, and custom tolerance`, () => {
			const doc = JSON.parse(
				readFileSync(new URL(`contracts/kinematics/${file}`, root), "utf8"),
			);
			const spec = doc.spec as LinkageSpec;
			installKinematicsKernel(wasm);
			expect(kinematicsKernel().name).toBe("rust-wasm/0.1.0");
			for (const sample of doc.samples) {
				const pose = solvePose(spec, sample.theta)!;
				for (const [id, point] of Object.entries(sample.points) as [
					string,
					[number, number],
				][]) {
					expect(pose[id]!.x).toBeCloseTo(point[0], 9);
					expect(pose[id]!.y).toBeCloseTo(point[1], 9);
				}
			}
			const path = trace(spec, 180);
			const reference = referenceKinematicsKernel.trace(spec, 180);
			expect(path.assembled).toBe(true);
			expect(path.poses).toHaveLength(180);
			expect(path.maxStep).toBeCloseTo(reference.maxStep, 9);
			for (let i = 0; i < path.poses.length; i++) {
				for (const [id, point] of Object.entries(path.poses[i]!)) {
					expect(point.x).toBeCloseTo(reference.poses[i]![id]!.x, 9);
					expect(point.y).toBeCloseTo(reference.poses[i]![id]!.y, 9);
				}
			}
			for (const tol of [0, 0.015, 0.1]) {
				const actual = gaitMetrics(path.foot, tol);
				const expected = referenceKinematicsKernel.gaitMetrics(
					reference.foot,
					tol,
				);
				for (const key of ["width", "lift", "strokeLength", "duty"] as const)
					expect(actual[key]).toBeCloseTo(expected[key], 9);
			}
		});
	}
	for (const caseData of boundaryCorpus.cases) {
		it(`boundary: ${caseData.name}`, () => {
			const spec = caseData.spec as LinkageSpec;
			const samples = caseData.samples ?? boundaryCorpus.samples;
			installKinematicsKernel(wasm);
			if (caseData.outcome === "error") {
				expect(() => trace(spec, samples)).toThrow();
				expect(() => referenceKinematicsKernel.trace(spec, samples)).toThrow();
			} else {
				const result = trace(spec, samples);
				expect(result.assembled).toBe(caseData.outcome === "assembled");
				expect(result.assembled).toBe(
					referenceKinematicsKernel.trace(spec, samples).assembled,
				);
				if (!result.assembled) {
					expect(result.foot).toEqual([]);
					expect(result.poses).toEqual([]);
					expect(result.maxStep).toBe(Infinity);
				}
			}
		});
	}
	it("rejects nonfinite/fractional sampling rather than truncating at the ABI", () => {
		installKinematicsKernel(wasm);
		const spec = boundaryCorpus.cases[0]!.spec as LinkageSpec;
		for (const samples of [0, -1, 1.5, NaN, Infinity, 1_000_001])
			expect(() => trace(spec, samples)).toThrow();
		expect(() => solvePose(spec, NaN)).toThrow();
		expect(() => gaitMetrics([{ x: Infinity, y: 0 }])).toThrow();
		expect(() => gaitMetrics([{ x: 0, y: 0 }], -1)).toThrow();
		expect(gaitMetrics([])).toEqual({
			width: 0,
			lift: 0,
			strokeLength: 0,
			duty: 0,
		});
	});
	it("never falls back if the installed kernel throws", () => {
		installKinematicsKernel({
			...wasm,
			solvePose() {
				throw new Error("kernel unavailable");
			},
		});
		expect(() =>
			solvePose(boundaryCorpus.cases[0]!.spec as LinkageSpec, 0),
		).toThrow("kernel unavailable");
		expect(kinematicsKernel().name).toBe("rust-wasm/0.1.0");
	});
	it("invalidates native handles on value changes and frees them without growing across a long edit loop", () => {
		const spec = structuredClone(boundaryCorpus.cases[0]!.spec) as LinkageSpec;
		installKinematicsKernel(wasm);
		const first = solvePose(spec, 0)!;
		spec.joints[0]!.side = -1;
		expect(solvePose(spec, 0)!.F!.y).toBeCloseTo(-first.F!.y, 9);
		spec.crank.x = 3.2;
		expect(solvePose(spec, 0)!.F!.x).not.toBe(first.F!.x);
		for (let i = 0; i < 100; i++) {
			spec.crank.x = 3 + (i % 2) * 0.01;
			trace(spec, 180);
		}
		const allocated = memory.buffer.byteLength;
		for (let i = 0; i < 1000; i++) {
			spec.crank.x = 3 + (i % 2) * 0.01;
			trace(spec, 180);
		}
		expect(memory.buffer.byteLength).toBe(allocated);
		wasm.dispose?.();
		expect(solvePose(spec, 0)).not.toBeNull(); // disposed adapters can explicitly create a fresh handle
	});
	it("keeps all 123 optimization fitness cases through the Rust engine", () => {
		installKinematicsKernel(wasm);
		for (const c of fitnessCorpus.cases) {
			const spec = fitnessCorpus.specs[
				c.spec as keyof typeof fitnessCorpus.specs
			] as unknown as LinkageSpec;
			const space = genomeSpace(spec);
			const penalty = infeasibility(space, c.genome);
			if (c.infeasibility === null) expect(penalty).toBeNull();
			else expect(penalty).toBeCloseTo(c.infeasibility, 9);
			for (const [fn, key] of [
				[fitnessFlatStroke, "flat"],
				[fitnessHighStep, "highstep"],
			] as const) {
				expect(fn(space)(c.genome)).toBeCloseTo(c[key], 9);
			}
		}
	});
});
