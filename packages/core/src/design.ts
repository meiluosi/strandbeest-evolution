import { JANSEN_LENGTHS, type JansenParams, jansenSpec } from "./jansen";
import type { LinkageSpec } from "./linkage";

/** The platform's Design document (schemas/design.schema.json). */
export interface Design {
	schema_version: 1;
	name: string;
	notes?: string;
	linkage: LinkageSpec;
	walker: {
		legs: number;
		unit_m: number;
		direction: -1 | 1;
		body_mass_kg: number;
		lateral_spacing_m?: number;
		body_length_m?: number;
	};
	drive: { kind: "motor" | "sail"; motor_omega_rad_s?: number };
	manufacturing: {
		process: "fdm";
		material: "PLA" | "PETG";
		bar_width_mm: number;
		bar_thickness_mm: number;
		pin_diameter_mm: number;
		clearance_mm: number;
		layer_height_mm?: number;
		min_wall_mm?: number;
		bed_mm?: [number, number];
	};
}

/** A small FDM-printable walker (1 length unit = 2 mm) built from the given lengths. */
export function defaultDesign(
	params: JansenParams = JANSEN_LENGTHS,
	name = "jansen-small-6leg",
): Design {
	return {
		schema_version: 1,
		name,
		notes:
			"Small FDM-printable Jansen walker (1 length unit = 2 mm). Motor-driven for bench tests.",
		linkage: jansenSpec(params),
		walker: {
			legs: 6,
			unit_m: 0.002,
			direction: -1,
			body_mass_kg: 0.35,
			lateral_spacing_m: 0.014,
			body_length_m: 0.25,
		},
		drive: { kind: "motor", motor_omega_rad_s: 2.0 },
		manufacturing: {
			process: "fdm",
			material: "PLA",
			bar_width_mm: 10,
			bar_thickness_mm: 3,
			pin_diameter_mm: 3,
			clearance_mm: 0.3,
			layer_height_mm: 0.2,
			min_wall_mm: 1.2,
			bed_mm: [220, 220],
		},
	};
}
