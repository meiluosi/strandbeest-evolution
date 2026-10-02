export interface Point {
	x: number;
	y: number;
}

/**
 * Intersection of circle(p0, r0) and circle(p1, r1).
 * `side` picks which of the two solutions: +1 is to the left of p0→p1, -1 to the right.
 * Returns null when the circles do not intersect (linkage cannot assemble).
 */
export function circleIntersection(
	p0: Point,
	r0: number,
	p1: Point,
	r1: number,
	side: 1 | -1,
): Point | null {
	const dx = p1.x - p0.x;
	const dy = p1.y - p0.y;
	const d = Math.hypot(dx, dy);
	if (d === 0 || d > r0 + r1 || d < Math.abs(r0 - r1)) return null;
	const a = (r0 * r0 - r1 * r1 + d * d) / (2 * d);
	const h = Math.sqrt(Math.max(0, r0 * r0 - a * a));
	const mx = p0.x + (a * dx) / d;
	const my = p0.y + (a * dy) / d;
	return { x: mx - (side * h * dy) / d, y: my + (side * h * dx) / d };
}
