import { circleIntersection, type Point } from "./geometry";

/** A number, or the name of an entry in `LinkageSpec.params`. */
export type ParamRef = string | number;

/** A joint solved as the intersection of two circles around earlier points. */
export interface JointDef {
	id: string;
	/** ids of the two points the circles are centred on (ground "G", crank tip "C", or earlier joints). */
	centers: [string, string];
	/** link lengths (param refs) for each circle. */
	radii: [ParamRef, ParamRef];
	/** which of the two circle intersections; fixes the assembly branch. */
	side: 1 | -1;
}

export interface LinkageSpec {
	params: Record<string, number>;
	/** ground pivot "G" is the origin; the crank pivot sits at (x, y) from it. */
	crank: { x: ParamRef; y: ParamRef; length: ParamRef };
	joints: JointDef[];
	/** id of the joint whose path we care about. */
	foot: string;
}

export type Pose = Record<string, Point>;

function val(spec: LinkageSpec, ref: ParamRef): number {
	if (typeof ref === "number") return ref;
	const v = spec.params[ref];
	if (v === undefined) throw new Error(`unknown param: ${ref}`);
	return v;
}

/** Solve every joint position for crank angle `theta` (radians). null = cannot assemble. */
export function solvePose(spec: LinkageSpec, theta: number): Pose | null {
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

export interface Trajectory {
	/** foot positions, one per crank angle; empty if any angle failed to assemble. */
	foot: Point[];
	poses: Pose[];
	assembled: boolean;
	/** largest jump between consecutive foot samples (large = likely branch flip). */
	maxStep: number;
}

/** Sample a full crank revolution at `samples` evenly spaced angles. */
export function trace(spec: LinkageSpec, samples = 120): Trajectory {
	const foot: Point[] = [];
	const poses: Pose[] = [];
	for (let i = 0; i < samples; i++) {
		const pose = solvePose(spec, (2 * Math.PI * i) / samples);
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
