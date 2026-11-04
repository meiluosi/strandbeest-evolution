import type { Point } from "./geometry";
import type { LinkageSpec, Pose, Trajectory } from "./linkage";
import type { GaitMetrics } from "./metrics";
import {
	referenceGaitMetrics,
	referenceSolvePose,
	referenceTrace,
} from "./reference-kinematics";
import type {
	StrideReference,
	StrideReferenceOptions,
} from "./stride-reference";

/** Host-independent synchronous numerical boundary. Loading WASM belongs to the host. */
export interface KinematicsKernel {
	readonly name: string;
	dispose?(): void;
	solvePose(spec: LinkageSpec, theta: number): Pose | null;
	trace(spec: LinkageSpec, samples: number): Trajectory;
	gaitMetrics(foot: Point[], tol: number): GaitMetrics;
	strideReference?(
		spec: LinkageSpec,
		options: StrideReferenceOptions,
	): StrideReference;
}

/** Explicit standalone-library default, kept separately for independent parity tests. */
export const referenceKinematicsKernel: KinematicsKernel = {
	name: "typescript-reference",
	solvePose: referenceSolvePose,
	trace: referenceTrace,
	gaitMetrics: referenceGaitMetrics,
};
let active = referenceKinematicsKernel;

export function installKinematicsKernel(kernel: KinematicsKernel): void {
	if (active !== kernel) active.dispose?.();
	active = kernel;
}

export function kinematicsKernel(): KinematicsKernel {
	return active;
}

/** The generated wasm-bindgen functions after explicit host initialization. */
export interface WasmKernelExports {
	Linkage: new (
		spec: string,
	) => {
		solve(theta: number): Float64Array;
		trace(samples: number): Float64Array;
		stride_reference_json(options: string): string;
		free(): void;
	};
	gait_flat(coordinates: Float64Array, tol: number): Float64Array;
	kernel_version(): string;
}

/** Pure adapter: no Node, DOM, fetching, or fallback. One owned handle per engine, keyed by all input values. */
export function createWasmKinematicsKernel(
	wasm: WasmKernelExports,
): KinematicsKernel {
	let cached:
		| {
				key: string;
				native: InstanceType<WasmKernelExports["Linkage"]>;
				ids: string[];
				foot: string;
		  }
		| undefined;
	const invoke = <T>(call: () => T): T => {
		try {
			return call();
		} catch (error) {
			throw error instanceof Error ? error : new Error(String(error));
		}
	};
	function prepare(spec: LinkageSpec) {
		const key = JSON.stringify(spec);
		if (cached?.key !== key) {
			const native = invoke(() => new wasm.Linkage(key));
			cached?.native.free();
			cached = {
				key,
				native,
				ids: ["G", "C", ...spec.joints.map((j) => j.id)],
				foot: spec.foot,
			};
		}
		return cached;
	}
	function unpack(flat: Float64Array, offset: number, ids: string[]): Pose {
		const pose: Pose = {};
		ids.forEach((id, i) => {
			pose[id] = { x: flat[offset + 2 * i]!, y: flat[offset + 2 * i + 1]! };
		});
		return pose;
	}
	return {
		name: `rust-wasm/${wasm.kernel_version()}`,
		dispose() {
			cached?.native.free();
			cached = undefined;
		},
		solvePose(spec, theta) {
			const { native, ids } = prepare(spec);
			const flat = invoke(() => native.solve(theta));
			return flat.length === 0 ? null : unpack(flat, 0, ids);
		},
		trace(spec, samples) {
			// wasm-bindgen's usize coercion would otherwise silently wrap negative/fractional input.
			if (!Number.isSafeInteger(samples) || samples <= 0 || samples > 1_000_000)
				throw new Error("samples must be in 1..=1000000");
			const { native, ids, foot } = prepare(spec);
			const flat = invoke(() => native.trace(samples));
			if (flat.length === 0)
				return { foot: [], poses: [], assembled: false, maxStep: Infinity };
			const poses: Pose[] = [];
			const points: Point[] = [];
			for (let i = 0; i < samples; i++) {
				const pose = unpack(flat, 1 + i * ids.length * 2, ids);
				poses.push(pose);
				points.push(pose[foot]!);
			}
			return { foot: points, poses, assembled: true, maxStep: flat[0]! };
		},
		gaitMetrics(foot, tol) {
			const coordinates = new Float64Array(foot.length * 2);
			foot.forEach((p, i) => {
				coordinates[2 * i] = p.x;
				coordinates[2 * i + 1] = p.y;
			});
			const result = invoke(() => wasm.gait_flat(coordinates, tol));
			return {
				width: result[0]!,
				lift: result[1]!,
				strokeLength: result[2]!,
				duty: result[3]!,
			};
		},
		strideReference(spec, options) {
			const { native } = prepare(spec);
			return JSON.parse(
				invoke(() => native.stride_reference_json(JSON.stringify(options))),
			) as StrideReference;
		},
	};
}
