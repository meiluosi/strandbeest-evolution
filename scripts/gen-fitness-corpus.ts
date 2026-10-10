// Regenerate contracts/fitness/cases.json from the TypeScript fitness functions (the reference); the Python port must match.
import { readFileSync, writeFileSync } from "node:fs";
import { createRng, fitnessFlatStroke, fitnessHighStep, genomeSpace, infeasibility, jansenSpec, type LinkageSpec } from "../packages/core/src";

const corpus = (n: string) => JSON.parse(readFileSync(`contracts/kinematics/${n}.json`, "utf8")).spec as LinkageSpec;
const specs: Record<string, LinkageSpec> = { jansen: jansenSpec(), "fourbar-crank-rocker": corpus("fourbar-crank-rocker"), "sixbar-extra-dyad": corpus("sixbar-extra-dyad") };
const rng = createRng(20261006);
const cases: unknown[] = [];
for (const [name, spec] of Object.entries(specs)) {
	const space = genomeSpace(spec);
	const flat = fitnessFlatStroke(space);
	const high = fitnessHighStep(space);
	const base = space.toGenome();
	const genomes = [base, ...Array.from({ length: 40 }, () => base.map((v) => v * (0.6 + 0.9 * rng())))];
	for (const g of genomes) cases.push({ spec: name, genome: g, flat: flat(g), highstep: high(g), infeasibility: infeasibility(space, g) });
}
writeFileSync("contracts/fitness/cases.json", `${JSON.stringify({ _doc: "Fitness values from packages/core (reference) for Jansen and two corpus chains; the Python port must match to 1e-9. Regenerate with scripts/gen-fitness-corpus.ts.", specs, cases })}\n`);
console.log(cases.length, "cases");
