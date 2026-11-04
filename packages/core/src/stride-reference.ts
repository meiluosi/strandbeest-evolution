import { kinematicsKernel } from "./kernel";
import type { LinkageSpec } from "./linkage";

/** Derived from Scenario + the built sphere owner; no physical defaults here. */
export interface StrideReferenceOptions {
	owner_start: string;
	phases_rad: number[];
	direction: -1 | 1;
	unit_m: number;
	radius_m: number;
	brackets: number;
}

export interface StrideReference {
	model: "lowest-foot-sphere-v1";
	status:
		| "estimated"
		| "unassembled"
		| "incompatible_supports"
		| "unresolved_sampling";
	brackets: number;
	support_switches: number;
	max_support_displacement_conflict_m: number;
	estimate: {
		point_stride_m_per_rev: number;
		rolling_m_per_rev: number;
		contact_stride_m_per_rev: number;
		sampled_absolute_contact_travel_m_per_rev: number;
		cancellation_condition: number | null;
	} | null;
}

/** Experimental rigid, flat, no-slip reference; not a physical acceptance gate.
 * Requires the Rust/WASM capability, and never falls back to another formula.
 * Compare sampling resolutions; tiny and zero displacements keep their sign/size.
 */
export function strideReference(
	spec: LinkageSpec,
	options: StrideReferenceOptions,
): StrideReference {
	const kernel = kinematicsKernel();
	if (!kernel.strideReference)
		throw new Error(
			"The active kernel has no signed stride reference capability",
		);
	return kernel.strideReference(spec, options);
}
