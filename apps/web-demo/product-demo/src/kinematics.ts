export type Point = { x: number; y: number };
export type Params = Record<string, number>;
export type Pose = Record<string, Point>;

export const DEFAULT_PARAMS: Params = {
	a: 38,
	b: 41.5,
	c: 39.3,
	d: 40.1,
	e: 55.8,
	f: 39.4,
	g: 36.7,
	h: 65.7,
	i: 49,
	j: 50,
	k: 61.9,
	l: 7.8,
	m: 15,
};

export const PARAM_GROUPS = [
	{
		title: "group.frame",
		hint: "group.frameHint",
		items: [
			["a", "param.a"],
			["l", "param.l"],
			["m", "param.m"],
		],
	},
	{
		title: "group.closed",
		hint: "group.closedHint",
		items: [
			["b", "param.b"],
			["j", "param.j"],
			["d", "param.d"],
			["e", "param.e"],
			["c", "param.c"],
			["k", "param.k"],
			["f", "param.f"],
			["g", "param.g"],
			["i", "param.i"],
			["h", "param.h"],
		],
	},
] as const;

const joints = [
	{ id: "K", centers: ["G", "C"], radii: ["b", "j"], side: 1 },
	{ id: "L", centers: ["G", "K"], radii: ["d", "e"], side: 1 },
	{ id: "M", centers: ["G", "C"], radii: ["c", "k"], side: -1 },
	{ id: "N", centers: ["L", "M"], radii: ["f", "g"], side: -1 },
	{ id: "F", centers: ["M", "N"], radii: ["i", "h"], side: 1 },
] as const;

export const LINKS: [string, string][] = [
	["G", "K"],
	["C", "K"],
	["G", "L"],
	["K", "L"],
	["G", "M"],
	["C", "M"],
	["L", "N"],
	["M", "N"],
	["M", "F"],
	["N", "F"],
];

function intersection(
	p0: Point,
	r0: number,
	p1: Point,
	r1: number,
	side: number,
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

export function solve(params: Params, theta: number): Pose | null {
	const pose: Pose = {
		G: { x: 0, y: 0 },
		P: { x: params.a!, y: params.l! },
		C: {
			x: params.a! + params.m! * Math.cos(theta),
			y: params.l! + params.m! * Math.sin(theta),
		},
	};
	for (const joint of joints) {
		const p0 = pose[joint.centers[0]];
		const p1 = pose[joint.centers[1]];
		if (!p0 || !p1) return null;
		const point = intersection(
			p0,
			params[joint.radii[0]]!,
			p1,
			params[joint.radii[1]]!,
			joint.side,
		);
		if (!point) return null;
		pose[joint.id] = point;
	}
	return pose;
}

export function trace(params: Params, samples = 180): Point[] {
	const points: Point[] = [];
	for (let i = 0; i < samples; i++) {
		const pose = solve(params, (i / samples) * Math.PI * 2);
		if (!pose) return [];
		points.push(pose.F!);
	}
	return points;
}

export function metrics(params: Params) {
	const foot = trace(params);
	if (!foot.length) return null;
	const xs = foot.map((p) => p.x);
	const ys = foot.map((p) => p.y);
	const lo = Math.min(...ys);
	const width = Math.max(...xs) - Math.min(...xs);
	const lift = Math.max(...ys) - lo;
	const ground = foot.map((p) => p.y <= lo + width * 0.015);
	let best = 0;
	let current = 0;
	for (let i = 0; i < ground.length * 2; i++) {
		current = ground[i % ground.length] ? current + 1 : 0;
		if (current <= ground.length) best = Math.max(best, current);
	}
	return { width, lift, duty: best / foot.length, stroke: width * 0.82 };
}

export function dragParams(
	params: Params,
	theta: number,
	id: string,
	point: Point,
): Params {
	const next = { ...params };
	const pose = solve(params, theta);
	if (!pose) return next;
	if (id === "P") {
		next.a = Math.round(point.x * 100) / 100;
		next.l = Math.round(point.y * 100) / 100;
		return next;
	}
	if (id === "C") {
		next.m = Math.max(3, Math.hypot(point.x - params.a!, point.y - params.l!));
		return next;
	}
	const joint = joints.find((item) => item.id === id);
	if (!joint) return next;
	joint.centers.forEach((center, index) => {
		const base = pose[center];
		if (base)
			next[joint.radii[index]] = Math.max(
				3,
				Math.hypot(point.x - base.x, point.y - base.y),
			);
	});
	return next;
}

export function svgPoint(point: Point): string {
	return `${point.x.toFixed(2)},${(-point.y).toFixed(2)}`;
}
