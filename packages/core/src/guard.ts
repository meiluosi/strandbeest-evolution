import type { LinkageSpec } from "./linkage";
import { solvePose } from "./linkage";
import { structureErrors } from "./validity";

/**
 * The validity guard, kinematic part (E3-02). Twin of strandbeest_common/guard.py; both are checked against
 * contracts/ops/cases.json. An operation is rejected when it introduces an error. See guard.py for the checks.
 */
export interface Problem {
	level: "error" | "warning";
	code: string;
	path: string;
	message: string;
}

export const SAMPLES = 72; // crank angles tested: every 5 degrees
export const JUMP_FRACTION = 0.2; // a point that moves more than this fraction of the leg size between samples is a suspect ...
export const REFINE = 16; // ... which is re-examined at 16 times the resolution
export const FLIP_FRACTION = 0.1; // a suspect is a real flip only if it still jumps more than this fraction of the size at that resolution

export function kinematicProblems(spec: LinkageSpec): Problem[] {
	const structural: Problem[] = structureErrors(spec).map((e) => ({
		level: "error",
		...e,
	}));
	if (structural.length) return structural;
	const poses: NonNullable<ReturnType<typeof solvePose>>[] = [];
	const failed: number[] = [];
	for (let i = 0; i < SAMPLES; i++) {
		const pose = solvePose(spec, (2 * Math.PI * i) / SAMPLES);
		if (pose) poses.push(pose);
		else failed.push(i);
	}
	if (failed.length) {
		const deg = [
			...new Set(failed.map((i) => Math.round((360 * i) / SAMPLES))),
		].sort((a, b) => a - b);
		const shown = deg.slice(0, 6).join(", ") + (deg.length > 6 ? " ..." : "");
		return [
			{
				level: "error",
				code: "cannot_assemble",
				path: "linkage",
				message: `the linkage cannot close at ${failed.length} of ${SAMPLES} crank angles (degrees: ${shown})`,
			},
		];
	}
	let size = 0;
	for (const pose of poses)
		for (const p of Object.values(pose))
			size = Math.max(size, Math.hypot(p.x, p.y));
	size = size || 1;
	// A point can move fast without flipping (near a dead point it moves like the square root of the crank angle). So a
	// big step between samples is only a suspect: refine it, and call it a flip if it is still a jump (or the linkage does
	// not close inside the interval, a window narrower than the sampling step).
	for (let i = 0; i < poses.length; i++) {
		const a = poses[i] as (typeof poses)[number];
		const b = poses[(i + 1) % poses.length] as typeof a;
		const dist = (p: { x: number; y: number }, q: { x: number; y: number }) =>
			Math.hypot(p.x - q.x, p.y - q.y);
		if (
			Math.max(
				...Object.keys(a).map((id) =>
					dist(
						a[id] as { x: number; y: number },
						b[id] as { x: number; y: number },
					),
				),
			) <=
			JUMP_FRACTION * size
		)
			continue;
		const sub = Array.from({ length: REFINE + 1 }, (_, k) =>
			solvePose(spec, (2 * Math.PI * (i + k / REFINE)) / SAMPLES),
		);
		if (sub.some((p) => p === null))
			return [
				{
					level: "error",
					code: "branch_flip",
					path: "linkage",
					message: `the linkage fails to close in a narrow window near ${Math.round((360 * i) / SAMPLES)} degrees of crank angle`,
				},
			];
		for (const id of Object.keys(a)) {
			let worst = 0;
			for (let k = 0; k < REFINE; k++)
				worst = Math.max(
					worst,
					dist(
						(sub[k] as NonNullable<(typeof sub)[number]>)[id] as {
							x: number;
							y: number;
						},
						(sub[k + 1] as NonNullable<(typeof sub)[number]>)[id] as {
							x: number;
							y: number;
						},
					),
				);
			if (worst > FLIP_FRACTION * size)
				return [
					{
						level: "error",
						code: "branch_flip",
						path: `joints.${id}`,
						message: `point ${id} still jumps ${Math.round((100 * worst) / size)}% of the leg size at ${(360 / SAMPLES / REFINE).toFixed(2)} degree resolution: the assembly branch flips`,
					},
				];
		}
	}
	return [];
}
