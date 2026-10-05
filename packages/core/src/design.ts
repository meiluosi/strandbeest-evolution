export type * from "./generated/design";

import type { Design } from "./generated/design";
import { legacyUlid, newUlid } from "./ids";
import { JANSEN_LENGTHS, type JansenParams, jansenSpec } from "./jansen";

/** A small FDM-printable walker (1 length unit = 2 mm) built from the given lengths. */
export function defaultDesign(
	params: JansenParams = JANSEN_LENGTHS,
	name = "jansen-small-6leg",
	id: string = newUlid(),
): Design {
	return {
		schema_version: 2,
		id,
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

/**
 * Upgrade a schema-v1 design document (identified by name) to v2. The id is derived from the name exactly as
 * strandbeest_common.migrate does, so the same file gets the same id in the browser and on the server.
 * A document that is already v2 is returned unchanged.
 */
export function migrateDesign(
	doc: { schema_version?: number; name?: string } & Record<string, unknown>,
): Design {
	if (doc.schema_version === 2) return doc as unknown as Design;
	if (doc.schema_version !== 1 || typeof doc.name !== "string")
		throw new Error("cannot migrate: not a schema v1 or v2 design");
	const { schema_version: _drop, ...rest } = doc;
	return {
		schema_version: 2,
		id: legacyUlid("design", doc.name),
		...rest,
	} as unknown as Design;
}
