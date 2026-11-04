/// <reference types="node" />
import { readFileSync } from "node:fs";
import { afterEach, beforeAll, expect, it } from "vitest";
import corpus from "../../../contracts/stride-reference/cases.json";
import * as bindings from "../../../crates/beest-kernel/generated/beest_kernel.js";
import {
	createWasmKinematicsKernel,
	installKinematicsKernel,
	referenceKinematicsKernel,
} from "./kernel";
import type { LinkageSpec } from "./linkage";
import {
	type StrideReferenceOptions,
	strideReference,
} from "./stride-reference";

let wasm: ReturnType<typeof createWasmKinematicsKernel>;
beforeAll(() => {
	bindings.initSync({
		module: readFileSync(
			new URL(
				"../../../crates/beest-kernel/generated/beest_kernel_bg.wasm",
				import.meta.url,
			),
		),
	});
	wasm = createWasmKinematicsKernel(bindings);
});
afterEach(() => installKinematicsKernel(referenceKinematicsKernel));

for (const row of corpus.cases) {
	it(`real WASM ${row.name}: matches the pre-existing independent geometric study`, () => {
		installKinematicsKernel(wasm);
		const result = strideReference(
			row.spec as unknown as LinkageSpec,
			row.options as StrideReferenceOptions,
		);
		expect(result.status).toBe("estimated");
		for (const [key, value] of Object.entries(row.expected)) {
			const actual = result.estimate![key as keyof typeof row.expected];
			expect(Math.abs(actual - value)).toBeLessThanOrEqual(corpus.tolerance_m);
		}
	});
}

it("keeps reverse, scaling, zero radius and mutable-spec changes in the native operation", () => {
	installKinematicsKernel(wasm);
	const row = structuredClone(corpus.cases[0]!);
	const spec = row.spec as unknown as LinkageSpec;
	const options = row.options as StrideReferenceOptions;
	const initial = strideReference(spec, options).estimate!;
	const reverse = strideReference(spec, {
		...options,
		direction: options.direction === 1 ? -1 : 1,
	}).estimate!;
	const scaled = strideReference(spec, {
		...options,
		unit_m: options.unit_m * 3,
		radius_m: options.radius_m * 3,
	}).estimate!;
	const point = strideReference(spec, { ...options, radius_m: 0 }).estimate!;
	const shifted = strideReference(spec, {
		...options,
		phases_rad: options.phases_rad.map((p) => p + 0.123),
	}).estimate!;
	for (const key of Object.keys(
		row.expected,
	) as (keyof typeof row.expected)[]) {
		expect(reverse[key]).toBe(-initial[key]);
		expect(Math.abs(scaled[key] - 3 * initial[key])).toBeLessThan(1e-14);
		expect(Math.abs(shifted[key] - initial[key])).toBeLessThan(1e-12);
	}
	expect(point.rolling_m_per_rev).toBe(0);
	expect(point.contact_stride_m_per_rev).toBe(initial.point_stride_m_per_rev);
	spec.params.a! *= 1.01;
	expect(
		Math.abs(
			strideReference(spec, options).estimate!.contact_stride_m_per_rev -
				initial.contact_stride_m_per_rev,
		),
	).toBeGreaterThan(1e-6);
});

it("rejects invalid inputs without ABI truncation or JSON null-to-zero coercion", () => {
	installKinematicsKernel(wasm);
	const row = corpus.cases[0]!;
	for (const change of [
		{ phases_rad: [] },
		{ phases_rad: [NaN] },
		{ direction: 0 },
		{ radius_m: -1 },
		{ unit_m: 0 },
		{ unit_m: Infinity },
		{ brackets: 1.5 },
		{ brackets: -1 },
		{ brackets: 1_000_001 },
		{ owner_start: "G" },
	]) {
		expect(() =>
			strideReference(
				row.spec as unknown as LinkageSpec,
				{ ...row.options, ...change } as StrideReferenceOptions,
			),
		).toThrow();
	}
});

it("reports nonassembly and propagates capability failures without formula fallback", () => {
	const row = structuredClone(corpus.cases[0]!);
	const spec = row.spec as unknown as LinkageSpec;
	const options = row.options as StrideReferenceOptions;
	expect(() => strideReference(spec, options)).toThrow(
		"no signed stride reference capability",
	);
	installKinematicsKernel(wasm);
	spec.params.b = 1e-8;
	const result = strideReference(spec, options);
	expect(result.status).toBe("unassembled");
	expect(result.estimate).toBeNull();
	installKinematicsKernel({
		...wasm,
		strideReference() {
			throw new Error("native unavailable");
		},
	});
	expect(() => strideReference(spec, options)).toThrow("native unavailable");
});
