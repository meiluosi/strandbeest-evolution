// CI: the static (Pages) build must ship one baked replay per scene, each with the fields the player reads.
// Usage: node scripts/check-static-build.mjs   (after `VITE_STATIC=1 pnpm --filter @strandbeest/web-demo build`)
import { existsSync, readFileSync } from "node:fs";

const dist = "apps/web-demo/dist";
const scenes = Object.keys(
	JSON.parse(readFileSync("contracts/scenes.json", "utf8")).scenes,
);
const need = ["t", "pos", "quat", "contact", "series", "metrics", "scene"];
const problems = [];
if (!existsSync(`${dist}/index.html`)) problems.push("no index.html");
for (const s of scenes) {
	const f = `${dist}/gallery/${s}.json`;
	if (!existsSync(f)) {
		problems.push(`missing ${f} (run scripts/bake-gallery.ts)`);
		continue;
	}
	const d = JSON.parse(readFileSync(f, "utf8"));
	for (const k of need) if (!(k in d)) problems.push(`${f}: no "${k}"`);
}
if (problems.length) {
	console.error(problems.join("\n"));
	process.exit(1);
}
console.log(`static build ok: ${scenes.length} baked scenes`);
