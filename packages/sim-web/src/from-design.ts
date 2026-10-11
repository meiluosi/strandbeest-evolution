/** Port of strandbeest_sim.from_design.scenario_from_design: a walker on flat ground, motor driven, from a Design. */
import type { Design } from "strandbeest-core";
import { type SimConfig, simConfig } from "./config";

// assumptions, mirrored from strandbeest_common.design (kg/m^3 solid, and the share that infill leaves)
const DENSITY_KG_M3: Record<string, number> = { PLA: 1240.0, PETG: 1270.0 };
const INFILL_FRACTION = 0.6;

export function barMassPerM(d: Design): number {
	const m = d.manufacturing;
	const area = m.bar_width_mm * 1e-3 * (m.bar_thickness_mm * 1e-3);
	return (DENSITY_KG_M3[m.material] as number) * INFILL_FRACTION * area;
}

export type Overrides = Record<string, unknown>;

export function scenarioFromDesign(
	design: Design,
	overrides: Overrides = {},
): SimConfig {
	const w = design.walker;
	const d = design.drive;
	const m = design.manufacturing;
	const unit = w.unit_m;
	const total = w.body_mass_kg + w.legs * 0.05; // rough, only used to scale the servo
	const sc: Record<string, Record<string, unknown>> & { name: string } = {
		name: design.name,
		linkage: { spec: design.linkage },
		walker: {
			legs: w.legs,
			body_mass: w.body_mass_kg,
			unit,
			direction: w.direction,
			tube_mass_per_m: barMassPerM(design),
			min_bar_mass: 1e-4,
			lateral_spacing: w.lateral_spacing_m ?? 0.014,
			body_length: w.body_length_m ?? 0.25,
			bar_radius: m.bar_width_mm / 2000.0,
			foot_radius: Math.max((m.bar_width_mm / 2000.0) * 0.4, 0.001),
			pitch: "locked",
		},
		drive: {
			kind: "motor",
			omega: d.motor_omega_rad_s ?? 2.0,
			kp: 200.0 * total * 9.81 * unit * 10,
			kv: 20.0 * total * 9.81 * unit * 10,
			ramp: 1.0,
			max_torque: 0.3,
		},
		solver: {
			timestep: 0.0001,
			solref_time: 0.001,
			solimp: "0.9 0.95 0.001",
			contact_stiffness: 3e5,
		},
		run: { settle: 0.5, revolutions: 1.5, record_every: 20 },
	} as never;
	const sail = d.sail ?? {};
	const sailMap: [string, keyof typeof sail][] = [
		["sail_area", "area_m2"],
		["sail_radius", "radius_m"],
		["sail_drag_coeff", "drag_coeff"],
		["sail_gear", "gear"],
		["rotor_inertia", "inertia_kg_m2"],
		["crank_damping", "damping_nm_s"],
		["crank_friction", "friction_nm"],
	];
	if (Object.keys(sail).length) {
		for (const [k, v] of sailMap)
			if (v in sail) (sc.drive as Record<string, unknown>)[k] = sail[v];
	}
	if (d.kind === "sail") {
		(sc.drive as Record<string, unknown>).kind = "sail";
		(sc.run as Record<string, unknown>).give_up_after = 8.0;
		(sc.run as Record<string, unknown>).max_time = 40.0;
	}
	for (const [key, val] of Object.entries(overrides)) {
		if (val !== null && typeof val === "object" && !Array.isArray(val))
			sc[key] = { ...(sc[key] ?? {}), ...(val as Record<string, unknown>) };
		else (sc as Record<string, unknown>)[key] = val;
	}
	return simConfig(sc);
}
