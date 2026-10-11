/** Port of strandbeest_sim.builder: LinkageSpec + SimConfig -> MJCF text. Read that file's docstring for the model: a planar
 *  tree of hinged bars per leg, loop closures as `connect` equalities, one shared crankshaft. The output must be byte-identical
 *  to the Python builder's (contracts/sim-mjcf), so number formatting and evaluation order mirror it on purpose. */
import { jansenSpec, type LinkageSpec, solvePose } from "strandbeest-core";
import type { SimConfig } from "./config";
import { fmtG9 as _f, pyFloat, pyInt } from "./pyfmt";

export interface Built {
	xml: string;
	n_legs: number;
	crank_joint: string;
	crank_q0: number;
	actuator: string;
	hip_height: number;
	bar_mass_total: number;
}

type P = { x: number; y: number };
interface Bar {
	name: string;
	start: string;
	end: string;
	mass: number;
}

/** The spec the scenario runs: its `linkage.spec` (a spec object, or "jansen") with `linkage.params` laid over the params. */
export function resolveSpec(sc: SimConfig): LinkageSpec {
	const src = sc.linkage.spec;
	const d: LinkageSpec =
		src === "jansen"
			? jansenSpec()
			: (JSON.parse(JSON.stringify(src)) as LinkageSpec);
	Object.assign(d.params, sc.linkage.params ?? {});
	return d;
}

const val = (spec: LinkageSpec, ref: string | number): number =>
	typeof ref === "number" ? ref : (spec.params[ref] as number);

export function buildMjcf(
	sc: SimConfig,
	spec: LinkageSpec,
	obstacles = "",
): Built {
	const w = sc.walker;
	const u = w.unit;
	const n = w.legs;
	const phases = Array.from({ length: n }, (_, i) => (2 * Math.PI * i) / n);
	const poses = phases.map((ph) => {
		const p = solvePose(spec, ph);
		if (!p)
			throw new Error("linkage cannot assemble at the initial crank angle");
		return p as Record<string, P>;
	});

	const lowest = Math.min(...poses.map((p) => (p[spec.foot] as P).y)) * u;
	const hipH = -lowest + w.foot_radius;
	const pinLoss =
		(w.joint_friction > 0 ? ` frictionloss="${_f(w.joint_friction)}"` : "") +
		(w.joint_damping > 0 ? ` damping="${_f(w.joint_damping)}"` : "");

	const massOf = (lengthUnits: number) =>
		Math.max(w.tube_mass_per_m * lengthUnits * u, w.min_bar_mass);
	const crankLen = val(spec, spec.crank.length);
	const crankMass = massOf(crankLen);
	let legBars = 0;
	for (const j of spec.joints)
		for (const r of j.radii) legBars += massOf(val(spec, r));
	const perLegMass = crankMass + legBars;
	const torsoMass =
		w.body_mass !== null && w.body_mass !== undefined
			? w.body_mass
			: w.mass - n * perLegMass;
	if (torsoMass <= 0)
		throw new Error(
			`legs weigh ${(n * perLegMass).toFixed(1)} kg, more than the total mass ${w.mass} kg`,
		);

	const eq: string[] = [];
	const torsoChildren: string[] = [];
	const px = val(spec, spec.crank.x);
	const py = val(spec, spec.crank.y);

	for (let i = 0; i < n; i++) {
		const pose = poses[i] as Record<string, P>;
		const y = (i - (n - 1) / 2) * w.lateral_spacing;
		const tip = pose.C as P;

		const barsAt = new Map<string, Bar[]>();
		const ownerOf = new Map<string, string>([["C", `crank${i}`]]);
		const byName = new Map<string, Bar>();
		for (const j of spec.joints) {
			j.centers.forEach((c, k) => {
				const b: Bar = {
					name: `bar${i}_${j.id}${k}`,
					start: c,
					end: j.id,
					mass: massOf(val(spec, j.radii[k] as string | number)),
				};
				if (!barsAt.has(c)) barsAt.set(c, []);
				(barsAt.get(c) as Bar[]).push(b);
				byName.set(b.name, b);
			});
			ownerOf.set(j.id, `bar${i}_${j.id}0`);
		}

		let footDone = false;
		const emit = (b: Bar, parent: [number, number], yOff: number): string => {
			const ps = pose[b.start] as P;
			const pe = pose[b.end] as P;
			const pos: [number, number, number] = [
				(ps.x - parent[0]) * u,
				yOff,
				(ps.y - parent[1]) * u,
			];
			const rel: [number, number] = [(pe.x - ps.x) * u, (pe.y - ps.y) * u];
			let geoms =
				`<geom type="capsule" fromto="0 0 0 ${_f(rel[0])} 0 ${_f(rel[1])}" size="${_f(w.bar_radius)}" mass="${_f(b.mass)}" ` +
				`contype="0" conaffinity="0" rgba="0.75 0.7 0.2 1"/>`;
			if (b.end === spec.foot && !footDone) {
				footDone = true; // both bars ending at the foot share one sphere
				geoms +=
					`<geom name="foot_${b.name}" type="sphere" pos="${_f(rel[0])} 0 ${_f(rel[1])}" size="${_f(w.foot_radius)}" ` +
					`mass="1e-6" friction="${_f(w.foot_friction)} 0.005 0.0001" contype="2" conaffinity="1" rgba="0.9 0.45 0.25 1"/>`;
			}
			let kids = "";
			if (ownerOf.get(b.end) === b.name)
				kids = (barsAt.get(b.end) ?? [])
					.map((c) => emit(c, [ps.x, ps.y], 0.0))
					.join("");
			return `<body name="${b.name}" pos="${_f(pos[0])} ${_f(pos[1])} ${_f(pos[2])}"><joint name="${b.name}" type="hinge" axis="0 1 0"${pinLoss}/>${geoms}${kids}</body>`;
		};

		for (const b of barsAt.get("G") ?? [])
			torsoChildren.push(emit(b, [0.0, 0.0], y));
		const crankVec: [number, number] = [(tip.x - px) * u, (tip.y - py) * u];
		const crankKids = (barsAt.get("C") ?? [])
			.map((b) => emit(b, [px, py], 0.0))
			.join("");
		torsoChildren.push(
			`<body name="crank${i}" pos="${_f(px * u)} ${_f(y)} ${_f(py * u)}">` +
				`<joint name="crank${i}" type="hinge" axis="0 1 0" ref="${_f(-(phases[i] as number))}"/>` +
				`<geom type="capsule" fromto="0 0 0 ${_f(crankVec[0])} 0 ${_f(crankVec[1])}" size="${_f(w.bar_radius)}" ` +
				`mass="${_f(crankMass)}" contype="0" conaffinity="0" rgba="0.2 0.2 0.25 1"/>${crankKids}</body>`,
		);

		for (const j of spec.joints) {
			const first = `bar${i}_${j.id}0`;
			const second = `bar${i}_${j.id}1`;
			const at = pose[j.id] as P;
			const s2 = pose[(byName.get(second) as Bar).start] as P;
			eq.push(
				`<connect body1="${second}" body2="${first}" anchor="${_f((at.x - s2.x) * u)} 0 ${_f((at.y - s2.y) * u)}"/>`,
			);
		}
		if (i > 0)
			eq.push(
				`<joint joint1="crank${i}" joint2="crank0" polycoef="0 1 0 0 0"/>`,
			);
	}

	const sv = sc.solver;
	const mt = sc.drive.max_torque;
	const forceAttr = mt
		? ` forcelimited="true" forcerange="${pyFloat(-mt)} ${pyFloat(mt)}"`
		: "";
	let geomSolref: string;
	if (sv.contact_stiffness !== null && sv.contact_stiffness !== undefined) {
		const mEff = (torsoMass + n * perLegMass) / 5.0;
		const damping =
			2.0 * sv.contact_damping_ratio * Math.sqrt(sv.contact_stiffness * mEff);
		geomSolref = `${pyFloat(-sv.contact_stiffness)} ${pyFloat(-damping)}`;
	} else geomSolref = `${pyFloat(sv.contact_solref)} 1`;
	const pitchJoint =
		w.pitch === "free" ? '<joint name="tp" type="hinge" axis="0 1 0"/>' : "";
	const halfY = Math.max((w.lateral_spacing * n) / 2, 0.05);
	const xml = `<mujoco model="${sc.name}">
  <compiler angle="radian"/>
  <option timestep="${pyFloat(sv.timestep)}" integrator="implicitfast" solver="Newton" iterations="${pyInt(sv.iterations)}" cone="${sv.cone}" impratio="${pyFloat(sv.impratio)}" noslip_iterations="${pyInt(sv.noslip_iterations)}" gravity="0 0 -${pyFloat(sc.environment.gravity)}"/>
  <default>
    <equality solref="${pyFloat(sv.solref_time)} 1" solimp="${sv.solimp}"/>
    <geom solref="${geomSolref}"/>
  </default>
  <worldbody>
    ${obstacles}
    <geom name="ground" type="plane" size="200 20 0.1" friction="${pyFloat(sc.terrain.friction)} 0.005 0.0001" contype="1" conaffinity="2" rgba="0.85 0.82 0.75 1"/>
    <body name="torso" pos="0 0 ${_f(hipH)}">
      <joint name="tx" type="slide" axis="1 0 0"/>
      <joint name="tz" type="slide" axis="0 0 1"/>
      ${pitchJoint}
      <geom type="box" size="${_f(w.body_length / 2)} ${_f(halfY)} 0.03" mass="${_f(torsoMass)}" contype="0" conaffinity="0" rgba="0.15 0.15 0.2 1"/>
      ${torsoChildren.join("")}
    </body>
  </worldbody>
  <equality>
    ${eq.join("")}
  </equality>
  <actuator>
    <position name="drive" joint="crank0" kp="${pyFloat(sc.drive.kp)}" kv="${pyFloat(sc.drive.kv)}" ctrlrange="-1e6 1e6"${forceAttr}/>
  </actuator>
</mujoco>`;
	return {
		xml,
		n_legs: n,
		crank_joint: "crank0",
		crank_q0: -(phases[0] as number),
		actuator: "drive",
		hip_height: hipH,
		bar_mass_total: n * perLegMass,
	};
}
