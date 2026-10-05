import type { LinkageSpec } from "./linkage";

/** Jansen's 13 lengths; m is the crank, a/l locate the crank pivot. Source: docs/RESEARCH-NOTES.md */
export const JANSEN_PARAM_NAMES = [
	"a",
	"b",
	"c",
	"d",
	"e",
	"f",
	"g",
	"h",
	"i",
	"j",
	"k",
	"l",
	"m",
] as const;
export type JansenParams = Record<(typeof JANSEN_PARAM_NAMES)[number], number>;

export const JANSEN_LENGTHS: JansenParams = {
	a: 38.0,
	b: 41.5,
	c: 39.3,
	d: 40.1,
	e: 55.8,
	f: 39.4,
	g: 36.7,
	h: 65.7,
	i: 49.0,
	j: 50.0,
	k: 61.9,
	l: 7.8,
	m: 15.0,
};

/**
 * Topology (arXiv 2606.22129, cross-checked by brute-force search for a flat-stroke foot path):
 * K=circ(C,j;G,b)  L=circ(K,e;G,d)  M=circ(C,k;G,c)  N=circ(L,f;M,g)  F=circ(M,i;N,h)
 * Branch signs are chosen so the foot is the lowest point of the leg (y up).
 */
export function jansenSpec(params: JansenParams = JANSEN_LENGTHS): LinkageSpec {
	return {
		params: { ...params },
		crank: { x: "a", y: "l", length: "m" },
		joints: [
			{ id: "K", centers: ["G", "C"], radii: ["b", "j"], side: 1 },
			{ id: "L", centers: ["G", "K"], radii: ["d", "e"], side: 1 },
			{ id: "M", centers: ["G", "C"], radii: ["c", "k"], side: -1 },
			{ id: "N", centers: ["L", "M"], radii: ["f", "g"], side: -1 },
			{ id: "F", centers: ["M", "N"], radii: ["i", "h"], side: 1 },
		],
		foot: "F",
	};
}

/** Jansen's 13 lengths as a genome (order of JANSEN_PARAM_NAMES) and back; for the reproduction experiments. */
export function genomeToParams(genome: number[]): JansenParams {
	const p = {} as JansenParams;
	JANSEN_PARAM_NAMES.forEach((name, i) => {
		p[name] = genome[i] as number;
	});
	return p;
}

export function paramsToGenome(p: JansenParams): number[] {
	return JANSEN_PARAM_NAMES.map((n) => p[n]);
}
