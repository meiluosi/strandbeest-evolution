// Dump poses of one crank revolution as JSON for the GIF renderer.  Usage: tsx scripts/export-poses.ts [out.json] [samples]
import { writeFileSync } from "node:fs";
import { JANSEN_LENGTHS, jansenSpec, trace } from "../packages/core/src";

const out = process.argv[2] ?? "docs/assets/jansen-poses.json";
const samples = Number(process.argv[3] ?? 120);
const t = trace(jansenSpec(), samples);
writeFileSync(
	out,
	JSON.stringify({
		pivot: { x: JANSEN_LENGTHS.a, y: JANSEN_LENGTHS.l },
		poses: t.poses,
		foot: t.foot,
	}),
);
console.log(out, t.poses.length);
