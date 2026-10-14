// Regenerate contracts/fitness/cases.json from the TypeScript fitness functions (the reference); the Python port must match.
import { readFileSync, writeFileSync } from "node:fs";
import {
	createRng,
	fitnessFlatStroke,
	fitnessHighStep,
	genomeSpace,
	infeasibility,
	jansenSpec,
	type LinkageSpec,
} from "../packages/core/src";

const corpus = (n: string) =>
	JSON.parse(readFileSync(`contracts/kinematics/${n}.json`, "utf8"))
		.spec as LinkageSpec;
const specs: Record<string, LinkageSpec> = {
	jansen: jansenSpec(),
	"fourbar-crank-rocker": corpus("fourbar-crank-rocker"),
	"sixbar-extra-dyad": corpus("sixbar-extra-dyad"),
};
const rng = createRng(20261006);
const cases: unknown[] = [];
for (const [name, spec] of Object.entries(specs)) {
	const space = genomeSpace(spec);
	const flat = fitnessFlatStroke(space);
	const high = fitnessHighStep(space);
	const base = space.toGenome();
	const genomes = [
		base,
		...Array.from({ length: 40 }, () =>
			base.map((v) => v * (0.6 + 0.9 * rng())),
		),
	];
	for (const g of genomes)
		cases.push({
			spec: name,
			genome: g,
			flat: flat(g),
			highstep: high(g),
			infeasibility: infeasibility(space, g),
		});
}
// Jansen's topology with lengths that assemble at all 24 probe angles but not at every one of the 90 trace samples (Q-06): the
// trace is empty. These used to give NaN in packages/core; every implementation must give the same finite penalty.
{
	const space = genomeSpace(specs.jansen as LinkageSpec);
	const flat = fitnessFlatStroke(space);
	const high = fitnessHighStep(space);
	const gaps = [
		[
			64.67385978307576, 29.80199082966428, 63.86976668846793,
			19.577371424413286, 29.826606977689078, 78.58843924420886,
			41.25715507077054, 83.70126896857052, 94.98323647822254,
			47.73498507332988, 77.22419129942776, 11.39348673437722,
			11.904553424566984,
		],
		[
			34.366972863534464, 63.55571660995483, 29.851557890705294,
			70.68231056968449, 18.292477572499774, 37.14387735323049,
			69.6257471730141, 59.745372706681955, 48.56062900244724,
			68.36524658137932, 52.832339021626396, 13.75637577057816,
			14.176675804308616,
		],
		[
			72.78333254582249, 74.24742717592744, 69.90260018100729,
			62.60442664255155, 78.74370916864369, 62.68100485262926,
			71.34663032348035, 65.88116650148062, 17.116744417650626,
			57.21410197555087, 118.13942682048072, 8.944690409777687,
			25.19380972359795,
		],
	];
	for (const g of gaps)
		cases.push({
			spec: "jansen",
			genome: g,
			flat: flat(g),
			highstep: high(g),
			infeasibility: infeasibility(space, g),
		});
}
writeFileSync(
	"contracts/fitness/cases.json",
	`${JSON.stringify({ _doc: "Fitness values from packages/core (reference) for Jansen and two corpus chains; the Python port must match to 1e-9. Regenerate with scripts/gen-fitness-corpus.ts.", specs, cases })}\n`,
);
console.log(cases.length, "cases");
