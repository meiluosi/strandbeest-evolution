/** Geometry-only study worker. JSON requests on stdin, real WASM results on stdout. */
import { readFileSync } from "node:fs";
import * as bindings from "../crates/beest-kernel/generated/beest_kernel.js";
import {
	createWasmKinematicsKernel,
	installKinematicsKernel,
} from "../packages/core/src/kernel";
import type { LinkageSpec } from "../packages/core/src/linkage";
import {
	type StrideReferenceOptions,
	strideReference,
} from "../packages/core/src/stride-reference";

const requests = JSON.parse(readFileSync(0, "utf8")) as {
	case: number;
	spec: LinkageSpec;
	options: StrideReferenceOptions;
	resolutions: number[];
}[];
bindings.initSync({
	module: readFileSync(
		new URL(
			"../crates/beest-kernel/generated/beest_kernel_bg.wasm",
			import.meta.url,
		),
	),
});
const kernel = createWasmKinematicsKernel(bindings);
installKinematicsKernel(kernel);
const start = performance.now();
const rows = requests.map((request) => ({
	case: request.case,
	results: request.resolutions.map((brackets) =>
		strideReference(request.spec, { ...request.options, brackets }),
	),
}));
kernel.dispose?.();
process.stdout.write(
	JSON.stringify({
		node: process.version,
		kernel: kernel.name,
		wall_ms: performance.now() - start,
		rows,
	}),
);
