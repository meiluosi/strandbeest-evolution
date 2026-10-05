import { JANSEN_LENGTHS, jansenSpec } from "./jansen";
import type { LinkageSpec } from "./linkage";
import { paramNames } from "./structure";

/**
 * The search space of an optimiser over one linkage topology: a genome is the list of its named lengths
 * (in declaration order), the topology and branch signs stay fixed. Derived from any LinkageSpec. (E3-01)
 */
export interface GenomeSpace {
	/** the spec whose topology (and unlisted fields) every genome is applied to */
	readonly base: LinkageSpec;
	readonly names: readonly string[];
	toSpec(genome: readonly number[]): LinkageSpec;
	toGenome(spec?: LinkageSpec): number[];
}

export function genomeSpace(base: LinkageSpec): GenomeSpace {
	const names = paramNames(base);
	return {
		base,
		names,
		toSpec(genome) {
			if (genome.length !== names.length)
				throw new Error(
					`genome has ${genome.length} values, expected ${names.length}`,
				);
			const params: Record<string, number> = {};
			names.forEach((n, i) => {
				params[n] = genome[i] as number;
			});
			return { ...base, params };
		},
		toGenome(spec = base) {
			return names.map((n) => {
				const v = spec.params[n];
				if (v === undefined) throw new Error(`spec has no length "${n}"`);
				return v;
			});
		},
	};
}

/** Jansen's 13-length space, for the reproduction experiments and as the default. */
export const JANSEN_SPACE: GenomeSpace = genomeSpace(
	jansenSpec(JANSEN_LENGTHS),
);
