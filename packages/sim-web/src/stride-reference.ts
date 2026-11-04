/** Experimental kinematic reference; intentionally not connected to the live audit.
 * A nonrotating torso rides on the lowest foot centres. Equal-weight fitting
 * reports incompatible supports explicitly rather than calling their average
 * an exact no-slip solution. A missing support gives no velocity estimate.
 */
export function fitSupportVelocity(velocities: readonly number[]) {
	if (!velocities.length)
		return { velocity: null, rmsSlip: null, spread: null };
	const sum = velocities.reduce((a, b) => a + b, 0);
	const velocity = sum === 0 ? 0 : -sum / velocities.length;
	return {
		velocity,
		rmsSlip: Math.sqrt(
			velocities.reduce((s, v) => s + (v + velocity) ** 2, 0) /
				velocities.length,
		),
		spread: Math.max(...velocities) - Math.min(...velocities),
	};
}

/** Integrate support intervals by exact foot endpoint displacement. Bisection
 * resolves support switches; callers must compare bracket counts for convergence.
 * This returns a signed distance, including tiny or zero results, without any
 * denominator floor or claim that the compliant dynamic walker must match it.
 */
export function lowestFootStride(
	foot: (angle: number) => { x: number; y: number },
	phases: readonly number[],
	direction: number,
	unit: number,
	brackets: number,
) {
	if (!phases.length) return { stride: null, switches: 0 };
	const support = (theta: number) => {
		let index = 0;
		let lowest = Number.POSITIVE_INFINITY;
		for (let j = 0; j < phases.length; j++) {
			const height = foot(theta + phases[j]!).y;
			if (height < lowest) {
				index = j;
				lowest = height;
			}
		}
		return index;
	};
	const boundaries = [0];
	let last = support(0);
	for (let i = 1; i <= brackets; i++) {
		let a = (2 * Math.PI * (i - 1)) / brackets;
		let b = (2 * Math.PI * i) / brackets;
		const following = support(b);
		if (following !== last) {
			for (let n = 0; n < 48; n++) {
				const middle = 0.5 * (a + b);
				if (support(middle) === last) a = middle;
				else b = middle;
			}
			boundaries.push(0.5 * (a + b));
		}
		last = following;
	}
	boundaries.push(2 * Math.PI);
	let stride = 0;
	for (let i = 1; i < boundaries.length; i++) {
		const a = boundaries[i - 1]!;
		const b = boundaries[i]!;
		const phase = phases[support(0.5 * (a + b))]!;
		stride -= direction * unit * (foot(b + phase).x - foot(a + phase).x);
	}
	return { stride, switches: boundaries.length - 2 };
}
