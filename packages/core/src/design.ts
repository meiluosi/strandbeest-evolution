export type * from "./generated/design";

import type { Design } from "./generated/design";
import { JANSEN_LENGTHS, type JansenParams, jansenSpec } from "./jansen";

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
