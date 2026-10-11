/** Port of strandbeest_sim.runner.run (motor drive) on MuJoCo WebAssembly: settle, drive for N revolutions, record a replay.
 *
 *  This is the *browser preview*: it records what the 3D replay needs (poses, foot contacts and loads, centre of mass, the
 *  crank series) and the gait metrics, and skips what costs the most in the Python run: the per-step power balance (energy
 *  account), events, diagnosis and the invariant audit. A preview is therefore labelled `quality: "browser-preview"`.
 *  Same engine version, same MJCF, same step order as Python, so the trajectory is the Python one (see run.test.ts). */
import type { MainModule } from "@mujoco/mujoco";
import { gaitMetrics, type LinkageSpec, trace } from "strandbeest-core";
import { buildMjcf, resolveSpec } from "./builder";
import type { SimConfig } from "./config";
import type { Replay, ReplayScene } from "./replay";
import { obstaclesXml, terrainPlan } from "./terrains";

export class RunCancelled extends Error {
	constructor() {
		super("cancelled");
	}
}

export interface RunOptions {
	/** called about every `yieldMs` with how far the run is (0..1 of the driven revolutions) */
	onProgress?: (p: {
		phase: "settle" | "drive";
		fraction: number;
		simTime: number;
	}) => void;
	/** checked at every yield; return true to stop */
	cancelled?: () => boolean;
	/** lets the host breathe (a worker handles messages); default: a macrotask hop */
	yieldNow?: () => Promise<void>;
	yieldMs?: number;
}

const r = (v: number, d: number) => {
	const k = 10 ** d;
	return Math.round(v * k) / k;
};
const R3 = (a: ArrayLike<number>, d: number, off = 0) => [
	r(a[off] as number, d),
	r(a[off + 1] as number, d),
	r(a[off + 2] as number, d),
];
const REV = 2 * Math.PI;
const GEOM = { SPHERE: 2, CAPSULE: 3, BOX: 6 };
const OBJ = { BODY: 1, JOINT: 3, GEOM: 5, ACTUATOR: 19 } as const;

function rotVecQuat(v: number[], q: ArrayLike<number>): number[] {
	// MuJoCo quaternion (w, x, y, z): v' = v + 2 w (u x v) + 2 u x (u x v), u = (x, y, z)
	const [w, x, y, z] = [
		q[0] as number,
		q[1] as number,
		q[2] as number,
		q[3] as number,
	];
	const [vx, vy, vz] = v as [number, number, number];
	const cx = y * vz - z * vy;
	const cy = z * vx - x * vz;
	const cz = x * vy - y * vx;
	return [
		vx + 2 * (w * cx + (y * cz - z * cy)),
		vy + 2 * (w * cy + (z * cx - x * cz)),
		vz + 2 * (w * cz + (x * cy - y * cx)),
	];
}

/** The gait window of metrics_builtin.gait: whole revolutions after the first, or everything for runs shorter than two. */
export function gaitWindow(
	t: number[],
	psi: number[],
	x: number[],
	torque: number[],
): Record<string, number | null> {
	const total = psi.length
		? ((psi.at(-1) as number) - (psi[0] as number)) / REV
		: 0;
	let lo: number;
	let hi: number;
	let steady: number;
	if (total >= 1.98) {
		const n = Math.max(1, Math.floor(total + 0.02) - 1);
		lo = REV;
		hi = Math.min(REV * (1 + n), psi.at(-1) as number);
		steady = 1;
	} else {
		lo = 0;
		hi = psi.length ? (psi.at(-1) as number) : 0;
		steady = 0;
	}
	let i0 = -1;
	let i1 = -1;
	for (let i = 0; i < psi.length; i++) {
		const p = psi[i] as number;
		if (p >= lo && p <= hi) {
			if (i0 < 0) i0 = i;
			i1 = i;
		}
	}
	if (i0 < 0 || i1 - i0 < 1 || (psi[i1] as number) - (psi[i0] as number) <= 0)
		return { stride_per_rev: null, mean_speed: null, steady_window: steady };
	const dpsi = (psi[i1] as number) - (psi[i0] as number);
	const seg = torque.slice(i0, i1 + 1);
	const mean = seg.reduce((a, b) => a + b, 0) / seg.length;
	const peak = Math.max(...seg);
	return {
		stride_per_rev: (((x[i1] as number) - (x[i0] as number)) / dpsi) * REV,
		mean_speed:
			((x[i1] as number) - (x[i0] as number)) /
			((t[i1] as number) - (t[i0] as number)),
		mean_torque: mean,
		peak_torque: peak,
		torque_ptp: peak - Math.min(...seg),
		steady_window: steady,
	};
}

export async function runPreview(
	mj: MainModule,
	sc: SimConfig,
	opts: RunOptions = {},
): Promise<Replay> {
	if (sc.drive.kind !== "motor")
		throw new Error(
			`the browser preview supports the motor drive, not '${sc.drive.kind}' (run it locally)`,
		);
	const spec: LinkageSpec = resolveSpec(sc);
	const plan = terrainPlan(sc);
	const built = buildMjcf(sc, spec, obstaclesXml(plan.obstacles));
	// biome-ignore lint/suspicious/noExplicitAny: the embind typings of MuJoCo expose most members as `any`
	const m: any = (mj.MjModel as any).from_xml_string(built.xml);
	// biome-ignore lint/suspicious/noExplicitAny: see above
	const d: any = new (mj.MjData as any)(m);
	const freeLater: { delete(): void }[] = [];
	const yieldNow =
		opts.yieldNow ?? (() => new Promise<void>((res) => setTimeout(res, 0)));
	const yieldMs = opts.yieldMs ?? 80;
	try {
		const id = (kind: number, name: string): number =>
			mj.mj_name2id(m, kind, name);
		// mj_id2name returns NULL for an unnamed object; the binding turns that NULL into the string at wasm address 0, which is
		// "emsc" in MuJoCo 3.14.0. No object in our models is named that, so read it as "no name" (Python gets None -> "").
		const name = (kind: number, i: number): string => {
			const s = mj.mj_id2name(m, kind, i);
			return s === "emsc" ? "" : s || "";
		};

		// terrain options the adapter applies to the model after loading
		if (plan.slopeDeg) {
			const a = (plan.slopeDeg * Math.PI) / 180;
			const g = sc.environment.gravity;
			const gv = m.opt.gravity;
			gv[0] = -g * Math.sin(a);
			gv[1] = 0;
			gv[2] = -g * Math.cos(a);
		}
		if (plan.softness) {
			const [k, c] = plan.softness;
			const solref = m.geom_solref;
			for (let i = 0; i < m.ngeom; i++)
				if (m.geom_bodyid[i] === 0 || m.geom_contype[i] === 2)
					[solref[2 * i], solref[2 * i + 1]] = [-k, -c];
		}
		const footGeoms: number[] = [];
		for (let g = 0; g < m.ngeom; g++)
			if (name(OBJ.GEOM, g).startsWith("foot_")) footGeoms.push(g);
		mj.mj_forward(m, d);

		const act = id(OBJ.ACTUATOR, built.actuator);
		const torso = id(OBJ.BODY, "torso");
		const jnt = id(OBJ.JOINT, built.crank_joint);
		const qadr = m.jnt_qposadr[jnt] as number;
		const dt = m.opt.timestep as number;
		const dir = sc.walker.direction;
		const q0 = built.crank_q0;
		const nb = m.nbody - 1;
		// out parameters of the C API live in wasm memory (README: "Working with Out Parameters")
		const f6buf = new mj.DoubleBuffer(6);
		const vel6buf = new mj.DoubleBuffer(6);
		freeLater.push(f6buf, vel6buf);

		// views into wasm memory go stale when it grows (frames allocate); fetch them again after every frame
		let ctrl = d.ctrl;
		let qpos = d.qpos;
		let aforce = d.actuator_force;
		const refresh = () => {
			ctrl = d.ctrl;
			qpos = d.qpos;
			aforce = d.actuator_force;
		};
		const psi = () => -dir * ((qpos[qadr] as number) - q0);
		const tau = () => -dir * (aforce[act] as number);

		let lastYield = performance.now();
		const maybeYield = async (
			phase: "settle" | "drive",
			fraction: number,
			simTime: number,
		) => {
			if (performance.now() - lastYield < yieldMs) return;
			opts.onProgress?.({ phase, fraction, simTime });
			await yieldNow();
			if (opts.cancelled?.()) throw new RunCancelled();
			lastYield = performance.now();
			refresh();
		};

		const settleSteps = Math.round(sc.run.settle / dt);
		for (let i = 0; i < settleSteps; i++) {
			ctrl[act] = q0; // MotorDrive.control(driving=False): hold the initial angle
			mj.mj_step(m, d);
			if ((i & 255) === 0) await maybeYield("settle", i / settleSteps, 0);
		}
		refresh();

		const psiStart = psi();
		const target = sc.run.revolutions * REV;
		const rec = sc.run.record_every;
		const frameEvery =
			sc.run.frame_rate > 0
				? Math.max(1, Math.round(1.0 / (sc.run.frame_rate * dt)))
				: 0;
		const tSer: number[] = [];
		const psiSer: number[] = [];
		const xSer: number[] = [];
		const tauSer: number[] = [];
		const fT: number[] = [];
		const fPos: number[][][] = [];
		const fQuat: number[][][] = [];
		const fContact: number[][] = [];
		const fFootPos: number[][][] = [];
		const fFootForce: number[][][] = [];
		const fFootSlip: number[][] = [];
		const fCom: number[][] = [];

		const recordFrame = (t: number) => {
			fT.push(r(t, 4));
			const xpos = d.xpos;
			const xquat = d.xquat;
			const bodies: number[][] = [];
			const quats: number[][] = [];
			for (let b = 0; b < nb; b++) {
				bodies.push(R3(xpos, 4, 3 * (b + 1)));
				quats.push([
					r(xquat[4 * (b + 1)], 4),
					r(xquat[4 * (b + 1) + 1], 4),
					r(xquat[4 * (b + 1) + 2], 4),
					r(xquat[4 * (b + 1) + 3], 4),
				]);
			}
			fPos.push(bodies);
			fQuat.push(quats);

			const index = new Map(footGeoms.map((g, k) => [g, k]));
			const nf = footGeoms.length;
			const force = Array.from({ length: nf }, () => [0, 0, 0]);
			const slip = new Array<number>(nf).fill(0);
			const touching = new Set<number>();
			const contacts = d.contact;
			const ncon = d.ncon as number;
			for (let i = 0; i < ncon; i++) {
				const c = contacts.get(i);
				const g1 = c.geom1 as number;
				const g2 = c.geom2 as number;
				touching.add(g1);
				touching.add(g2);
				const foot = index.has(g2) ? g2 : index.has(g1) ? g1 : -1;
				if (foot >= 0) {
					const sign = foot === g2 ? 1 : -1;
					mj.mj_contactForce(m, d, i, f6buf);
					const f6 = f6buf.GetView();
					const fr = c.frame;
					const n = [fr[0] as number, fr[1] as number, fr[2] as number];
					const f = [0, 1, 2].map(
						(a) =>
							sign *
							(f6[0]! * fr[a]! + f6[1]! * fr[3 + a]! + f6[2]! * fr[6 + a]!),
					);
					const k = index.get(foot) as number;
					const fk = force[k] as number[];
					fk[0] = (fk[0] as number) + (f[0] as number);
					fk[1] = (fk[1] as number) + (f[1] as number);
					fk[2] = (fk[2] as number) + (f[2] as number);
					mj.mj_objectVelocity(m, d, OBJ.GEOM, foot, vel6buf, 0);
					const vel6 = vel6buf.GetView();
					const gx = d.geom_xpos;
					const cp = c.pos;
					const rel = [
						cp[0] - gx[3 * foot],
						cp[1] - gx[3 * foot + 1],
						cp[2] - gx[3 * foot + 2],
					];
					const rot = [vel6[0] as number, vel6[1] as number, vel6[2] as number];
					const v = [
						(vel6[3] as number) + (rot[1]! * rel[2]! - rot[2]! * rel[1]!),
						(vel6[4] as number) + (rot[2]! * rel[0]! - rot[0]! * rel[2]!),
						(vel6[5] as number) + (rot[0]! * rel[1]! - rot[1]! * rel[0]!),
					];
					const vn = v[0]! * n[0]! + v[1]! * n[1]! + v[2]! * n[2]!;
					const vt = Math.hypot(
						v[0]! - vn * n[0]!,
						v[1]! - vn * n[1]!,
						v[2]! - vn * n[2]!,
					);
					slip[k] = Math.max(slip[k] as number, vt);
				}
				c.delete?.();
			}
			contacts.delete?.();
			fContact.push(footGeoms.map((g) => (touching.has(g) ? 1 : 0)));
			const gx = d.geom_xpos;
			fFootPos.push(footGeoms.map((g) => R3(gx, 4, 3 * g)));
			fFootForce.push(force.map((f) => f.map((v) => r(v, 3))));
			fFootSlip.push(slip.map((s) => r(s, 4)));
			const com = d.subtree_com;
			fCom.push(R3(com, 4, 0));
			refresh();
		};

		let k = 0;
		let t = 0;
		let stalled = false;
		while (psi() - psiStart < target) {
			// MotorDrive.control(driving=True): smooth start-up ramp on the servo target
			const f0 = sc.drive.ramp <= 0 ? 1.0 : Math.min(t / sc.drive.ramp, 1.0);
			const f = f0 * f0 * (3 - 2 * f0);
			ctrl[act] = (ctrl[act] as number) + -dir * f * sc.drive.omega * dt;
			mj.mj_step(m, d);
			t += dt;
			if (k % rec === 0) {
				tSer.push(t);
				psiSer.push(psi() - psiStart);
				xSer.push(d.xpos[3 * torso] as number);
				tauSer.push(tau());
			}
			if (frameEvery && k % frameEvery === 0) recordFrame(t);
			k++;
			if (t > sc.run.max_time) {
				stalled = true;
				break;
			}
			if (
				sc.run.give_up_after &&
				t > sc.run.give_up_after &&
				psi() - psiStart < 0.1
			) {
				stalled = true;
				break;
			}
			if ((k & 255) === 0)
				await maybeYield("drive", Math.min(1, (psi() - psiStart) / target), t);
		}

		const scene = describeScene(m, name, plan.slopeDeg);
		const sstep = Math.max(1, Math.floor(tSer.length / 500));
		const pick = (a: number[], dgt: number) =>
			a.filter((_, i) => i % sstep === 0).map((v) => r(v, dgt));
		const fstep = Math.max(1, Math.floor(fT.length / 240));
		const sub = <T>(a: T[]) => a.filter((_, i) => i % fstep === 0);
		const metrics = {
			...gaitWindow(tSer, psiSer, xSer, tauSer),
			max_loop_violation: null,
			max_penetration: null,
		};
		let nominal: number | null = null;
		let duty: number | null = null;
		try {
			const g = gaitMetrics(trace(spec, 180).foot);
			duty = g.duty;
			nominal = g.duty > 0 ? (g.strokeLength / g.duty) * sc.walker.unit : null;
		} catch {
			/* a linkage that does not assemble has no kinematic stride */
		}
		return {
			scene,
			t: sub(fT),
			pos: sub(fPos),
			quat: sub(fQuat),
			contact: sub(fContact),
			foot_pos: sub(fFootPos),
			foot_force: sub(fFootForce),
			foot_slip: sub(fFootSlip),
			com: sub(fCom),
			series: {
				t: pick(tSer, 5),
				psi: pick(psiSer, 5),
				x: pick(xSer, 5),
				torque: pick(tauSer, 5),
			},
			energy: null,
			events: [],
			diagnosis: [],
			metrics,
			stalled,
			nominal_stride_m: nominal,
			kinematic_duty: duty,
			revolutions: (psiSer.at(-1) ?? 0) / REV,
			info: {
				terrain: {
					kind: sc.terrain.kind,
					slope_deg: sc.terrain.slope_deg,
					params: sc.terrain.params,
				},
				drive: sc.drive.kind,
				wind: sc.wind,
				environment: sc.environment,
				legs: sc.walker.legs,
				max_torque: sc.drive.max_torque,
			},
			quality: "browser-preview",
		};
	} finally {
		for (const b of freeLater) b.delete();
		d.delete?.();
		m.delete?.();
	}
}

// biome-ignore lint/suspicious/noExplicitAny: embind model
function describeScene(
	m: any,
	name: (kind: number, i: number) => string,
	slopeDeg: number,
): ReplayScene {
	const bodies: string[] = [];
	for (let i = 1; i < m.nbody; i++) bodies.push(name(OBJ.BODY, i));
	const geoms: ReplayScene["geoms"] = [];
	const obstacles: ReplayScene["obstacles"] = [];
	for (let g = 0; g < m.ngeom; g++) {
		const type = m.geom_type[g] as number;
		const body = m.geom_bodyid[g] as number;
		const rgba = Array.from({ length: 4 }, (_, i) =>
			r(m.geom_rgba[4 * g + i], 3),
		);
		const pos = [
			m.geom_pos[3 * g],
			m.geom_pos[3 * g + 1],
			m.geom_pos[3 * g + 2],
		] as number[];
		const quat = [
			m.geom_quat[4 * g],
			m.geom_quat[4 * g + 1],
			m.geom_quat[4 * g + 2],
			m.geom_quat[4 * g + 3],
		] as number[];
		const size = [
			m.geom_size[3 * g],
			m.geom_size[3 * g + 1],
			m.geom_size[3 * g + 2],
		] as number[];
		const gname = name(OBJ.GEOM, g);
		if (body === 0) {
			if (type === GEOM.BOX)
				obstacles.push({
					pos: pos.map((v) => r(v, 4)),
					size: size.map((v) => r(v, 4)),
					name: gname,
				});
			continue;
		}
		const item = {
			body: body - 1,
			name: gname,
			rgba,
			foot: gname.startsWith("foot_"),
		} as ReplayScene["geoms"][number];
		if (type === GEOM.CAPSULE) {
			const axis = rotVecQuat([0, 0, size[1] as number], quat);
			Object.assign(item, {
				type: "capsule",
				a: pos.map((v, i) => r(v - (axis[i] as number), 5)),
				b: pos.map((v, i) => r(v + (axis[i] as number), 5)),
				radius: r(size[0] as number, 5),
			});
		} else if (type === GEOM.SPHERE)
			Object.assign(item, {
				type: "sphere",
				pos: pos.map((v) => r(v, 5)),
				radius: r(size[0] as number, 5),
			});
		else if (type === GEOM.BOX)
			Object.assign(item, {
				type: "box",
				pos: pos.map((v) => r(v, 5)),
				quat: quat.map((v) => r(v, 6)),
				size: size.map((v) => r(v, 5)),
			});
		else continue;
		geoms.push(item);
	}
	return { bodies, geoms, obstacles, slope_deg: slopeDeg };
}
