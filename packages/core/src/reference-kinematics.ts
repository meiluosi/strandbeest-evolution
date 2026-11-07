/** Explicit, independent TypeScript reference. Used by pure-TS library consumers and migration parity.
 * Browser application and workers install Rust/WASM before using any core operations.
 * No kernel error is caught here or silently routed back to this implementation.
 */
import { circleIntersection, type Point } from "./geometry";
import type { LinkageSpec, ParamRef, Pose, Trajectory } from "./linkage";
import type { GaitMetrics } from "./metrics";
import { structureErrors } from "./validity";

function validate(spec: LinkageSpec) {
	const errors = structureErrors(spec);
	if (errors.length) throw new Error(errors[0]?.message);
	const refs = [
		spec.crank.x,
		spec.crank.y,
		spec.crank.length,
		...spec.joints.flatMap((j) => j.radii),
	];
	if (
		[...Object.values(spec.params), ...refs.map((r) => val(spec, r))].some(
			(v) => !Number.isFinite(v),
		)
	)
		throw new Error("parameters must be finite");
	if (spec.joints.some((j) => j.side !== -1 && j.side !== 1))
		throw new Error("side must be -1 or 1");
}

export function referenceSolvePose(
	spec: LinkageSpec,
	theta: number,
): Pose | null {
	validate(spec);
	if (!Number.isFinite(theta)) throw new Error("theta must be finite");
	return solvePoseUnchecked(spec, theta);
}

function val(spec: LinkageSpec, ref: ParamRef): number {
	if (typeof ref === "number") return ref;
	const v = spec.params[ref];
	if (v === undefined) throw new Error(`unknown param: ${ref}`);
	return v;
}

/** Solve every joint position for crank angle `theta` (radians). null = cannot assemble. */
function solvePoseUnchecked(spec: LinkageSpec, theta: number): Pose | null {
	const pivot = { x: val(spec, spec.crank.x), y: val(spec, spec.crank.y) };
	const r = val(spec, spec.crank.length);
	const pose: Pose = {
		G: { x: 0, y: 0 },
		C: { x: pivot.x + r * Math.cos(theta), y: pivot.y + r * Math.sin(theta) },
	};
	for (const j of spec.joints) {
		const p0 = pose[j.centers[0]];
		const p1 = pose[j.centers[1]];
		if (!p0 || !p1)
			throw new Error(`joint ${j.id} references an unsolved point`);
		const p = circleIntersection(
			p0,
			val(spec, j.radii[0]),
			p1,
			val(spec, j.radii[1]),
			j.side,
		);
		if (!p) return null;
		pose[j.id] = p;
	}
	return pose;
}

/** Sample a full crank revolution at `samples` evenly spaced angles. */
export function referenceTrace(spec: LinkageSpec, samples = 120): Trajectory {
	validate(spec);
	if (!Number.isSafeInteger(samples) || samples <= 0 || samples > 1_000_000)
		throw new Error("samples must be in 1..=1000000");
	const foot: Point[] = [];
	const poses: Pose[] = [];
	for (let i = 0; i < samples; i++) {
		const pose = solvePoseUnchecked(spec, (2 * Math.PI * i) / samples);
		if (!pose)
			return {
				foot: [],
				poses: [],
				assembled: false,
				maxStep: Number.POSITIVE_INFINITY,
			};
		poses.push(pose);
		const f = pose[spec.foot];
		if (!f) throw new Error(`foot joint ${spec.foot} not found`);
		foot.push(f);
	}
	let maxStep = 0;
	for (let i = 0; i < samples; i++) {
		const a = foot[i] as Point;
		const b = foot[(i + 1) % samples] as Point;
		maxStep = Math.max(maxStep, Math.hypot(a.x - b.x, a.y - b.y));
	}
	return { foot, poses, assembled: true, maxStep };
}
/**
 * Longest contiguous (cyclic) arc of the loop whose y stays within `tol * width` of the lowest point.
 * The tolerance scales with width, not lift, so a taller loop does not get a looser definition of "flat".
 * y is up, so the ground stroke is the bottom of the loop.
 */
export function referenceGaitMetrics(foot: Point[], tol = 0.015): GaitMetrics {
	if (
		!Number.isFinite(tol) ||
		tol < 0 ||
		foot.some((p) => !Number.isFinite(p.x) || !Number.isFinite(p.y))
	)
		throw new Error(
			"points must be finite and tolerance finite and nonnegative",
		);
	const n = foot.length;
	if (n === 0) return { width: 0, lift: 0, strokeLength: 0, duty: 0 };
	let boundMinX = Number.POSITIVE_INFINITY;
	let boundMaxX = Number.NEGATIVE_INFINITY;
	let minY = Number.POSITIVE_INFINITY;
	let maxY = Number.NEGATIVE_INFINITY;
	for (let i = 0; i < n; i++) {
		const p = foot[i] as Point;
		if (p.x < boundMinX) boundMinX = p.x;
		if (p.x > boundMaxX) boundMaxX = p.x;
		if (p.y < minY) minY = p.y;
		if (p.y > maxY) maxY = p.y;
	}
	const lo = minY;
	const lift = maxY - lo;
	const width = boundMaxX - boundMinX;
	const limit = lo + tol * width;
	const onGround = foot.map((p) => p.y <= limit);
	if (onGround.every(Boolean))
		return { width, lift, strokeLength: width, duty: 1 };

	let best = 0;
	let bestStart = 0;
	let run = 0;
	let runStart = 0;
	// walk the loop twice so a run crossing index 0 is counted whole
	for (let i = 0; i < 2 * n; i++) {
		if (onGround[i % n]) {
			if (run === 0) runStart = i;
			run++;
			if (run > best && run <= n) {
				best = run;
				bestStart = runStart;
			}
		} else run = 0;
	}
	let minX = Number.POSITIVE_INFINITY;
	let maxX = Number.NEGATIVE_INFINITY;
	for (let i = 0; i < best; i++) {
		const x = (foot[(bestStart + i) % n] as Point).x;
		minX = Math.min(minX, x);
		maxX = Math.max(maxX, x);
	}
	return {
		width,
		lift,
		strokeLength: best > 0 ? maxX - minX : 0,
		duty: best / n,
	};
}
