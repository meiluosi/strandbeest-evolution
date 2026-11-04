import type { Point } from "./geometry";
import { kinematicsKernel } from "./kernel";

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

export interface Trajectory {
	/** foot positions, one per crank angle; empty if any angle failed to assemble. */
	foot: Point[];
	poses: Pose[];
	assembled: boolean;
	/** largest jump between consecutive foot samples (large = likely branch flip). */
	maxStep: number;
}

/** Dispatch through the selected engine. Standalone core explicitly defaults to the isolated TS reference. */
export function solvePose(spec: LinkageSpec, theta: number): Pose | null {
	return kinematicsKernel().solvePose(spec, theta);
}

export function trace(spec: LinkageSpec, samples = 120): Trajectory {
	return kinematicsKernel().trace(spec, samples);
}
