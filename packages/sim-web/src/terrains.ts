/** Port of strandbeest_sim.terrains + the obstacle MJCF of the MuJoCo adapter: backend-neutral plans, then text. */
import type { SimConfig } from "./config";
import { pyFloat } from "./pyfmt";
import { PyRandom } from "./pyrandom";

export type Vec3 = [number, number, number];
export interface Box {
	name: string;
	pos: Vec3;
	size: Vec3;
	friction: number;
	/** the Python side puts int literals (0 and 5) in the y slots; they print without ".0" */
	intSlots?: boolean;
}
export interface TerrainPlan {
	obstacles: Box[];
	slopeDeg: number;
	softness: [number, number] | null;
}
const plan = (p: Partial<TerrainPlan> = {}): TerrainPlan => ({
	obstacles: [],
	slopeDeg: 0,
	softness: null,
	...p,
});
const num = (v: unknown, d: number) =>
	v === undefined || v === null ? d : Number(v);

export function terrainPlan(sc: SimConfig): TerrainPlan {
	const t = sc.terrain;
	const p = t.params;
	switch (t.kind) {
		case "flat":
			return plan();
		case "slope":
			return plan({ slopeDeg: t.slope_deg });
		case "step": {
			const d = num(p.distance, 0.5);
			const h = num(p.height, 0.02);
			const length = num(p.length, 1.0);
			return plan({
				obstacles: [
					{
						name: "step",
						pos: [d + length / 2, 0, h / 2],
						size: [length / 2, 5, h / 2],
						friction: t.friction,
						intSlots: true,
					},
				],
			});
		}
		case "bumps": {
			const rng = new PyRandom(Math.trunc(num(p.seed, 1)));
			const n = Math.trunc(num(p.count, 12));
			const hmax = num(p.max_height, 0.015);
			let x = num(p.start, 0.4);
			const out: Box[] = [];
			for (let i = 0; i < n; i++) {
				const w = rng.uniform(0.04, 0.12);
				const h = rng.uniform(0.2, 1.0) * hmax;
				out.push({
					name: `bump${i}`,
					pos: [x + w / 2, 0, h / 2],
					size: [w / 2, 5, h / 2],
					friction: t.friction,
					intSlots: true,
				});
				x += w + rng.uniform(0.05, 0.3);
			}
			return plan({ obstacles: out });
		}
		case "soft":
			return plan({
				softness: [num(p.stiffness, 4000.0), num(p.damping, 120.0)],
			});
		case "ramp": {
			const start = num(p.start, 0.3);
			const height = num(p.height, 0.03);
			const length = num(p.length, 0.25);
			const angle = num(p.angle_deg, 20.0);
			const mid = start + length / 2;
			const z = height / 2 + (length / 2) * Math.sin((angle * Math.PI) / 180);
			return plan({
				obstacles: [
					{
						name: "ramp",
						pos: [mid, 0, z],
						size: [length / 2, 5, height / 2],
						friction: t.friction,
						intSlots: true,
					},
				],
			});
		}
		default:
			throw new Error(`unknown terrain '${t.kind}'`);
	}
}

const OBSTACLE =
	'type="box" contype="1" conaffinity="2" rgba="0.62 0.58 0.5 1"';

export function obstaclesXml(boxes: Box[]): string {
	const f = (v: number, slot: number, b: Box) =>
		b.intSlots && slot === 1 ? String(v) : pyFloat(v);
	return boxes
		.map(
			(b) =>
				`<geom name="${b.name}" ${OBSTACLE} friction="${pyFloat(b.friction)} 0.005 0.0001" ` +
				`pos="${f(b.pos[0], 0, b)} ${f(b.pos[1], 1, b)} ${f(b.pos[2], 2, b)}" size="${f(b.size[0], 0, b)} ${f(b.size[1], 1, b)} ${f(b.size[2], 2, b)}"/>`,
		)
		.join("");
}
