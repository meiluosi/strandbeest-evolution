/**
 * Frame mappings, the single implementation (see docs/CONVENTIONS.md).
 *
 * hip frame (2D):   x forward, y up
 * world frame:      x forward, y lateral, z up         (MuJoCo, replay frames)
 * three.js frame:   x forward, y up, z = -world y      (a rotation by -90 degrees about x, not a mirror)
 */
export type Vec3 = [number, number, number];

/** world (MuJoCo) -> three.js */
export function worldToThree([x, y, z]: Vec3): Vec3 {
	return [x, z, -y];
}

/** three.js -> world (inverse of worldToThree) */
export function threeToWorld([x, y, z]: Vec3): Vec3 {
	return [x, -z, y];
}

/** hip-frame point (length units) -> world position in metres, given hip height and a lateral offset. */
export function hipToWorld(
	p: { x: number; y: number },
	unitM: number,
	hipHeightM: number,
	lateralM = 0,
): Vec3 {
	return [p.x * unitM, lateralM, hipHeightM + p.y * unitM];
}

/** crank angle relations: theta = direction * psi, q = -theta */
export function psiToTheta(psi: number, direction: -1 | 1): number {
	return direction * psi;
}
export function thetaToMujocoQ(theta: number): number {
	return -theta;
}
