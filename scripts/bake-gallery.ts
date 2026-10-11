// Bake one replay per scene for the static (backend-free) web demo.
// Needs a running `strandbeest-api` (STRANDBEEST_API, default http://127.0.0.1:8000).
// Usage: tsx scripts/bake-gallery.ts [scene ...]   -> apps/web-demo/public/gallery/<scene>.json + index.json
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { defaultDesign } from "../packages/core/src";

const api = process.env.STRANDBEEST_API ?? "http://127.0.0.1:8000";
const out = "apps/web-demo/public/gallery";
const scenes = JSON.parse(readFileSync("contracts/scenes.json", "utf8"))
	.scenes as Record<string, { sail?: boolean; ov: Record<string, any> }>;
const WIND = 3; // same default as the live scene player

async function call(path: string, body?: unknown) {
	const r = await fetch(api + path, {
		method: body === undefined ? "GET" : "POST",
		headers: { "content-type": "application/json" },
		body: body === undefined ? undefined : JSON.stringify(body),
	});
	if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
	return r.json() as Promise<any>;
}

async function runJob(path: string, body: unknown) {
	const { job_id } = await call(path, body);
	for (;;) {
		const j = await call(`/jobs/${job_id}`);
		if (j.status === "done") return j.result;
		if (j.status === "failed" || j.status === "cancelled")
			throw new Error(j.error ?? j.status);
		await new Promise((r) => setTimeout(r, 1000));
	}
}

async function main() {
	mkdirSync(out, { recursive: true });
	const wanted = process.argv.slice(2);
	const baked: string[] = [];
	for (const [key, sc] of Object.entries(scenes)) {
		if (wanted.length && !wanted.includes(key)) continue;
		// mirrors ScenePlayer.run() so a baked replay is what the live button would have produced
		const ov = JSON.parse(JSON.stringify(sc.ov));
		ov.run = { settle: 0.5, revolutions: 2, frame_rate: 30, ...(ov.run ?? {}) };
		if (sc.sail) {
			ov.drive = { kind: "sail", ...(ov.drive ?? {}) };
			ov.wind = { ...(ov.wind ?? {}), speed: WIND };
			ov.run = { ...ov.run, give_up_after: 6, max_time: 30 };
		}
		const t0 = Date.now();
		const doc = await runJob("/runs", {
			design: defaultDesign(),
			ensemble: false,
			overrides: ov,
		});
		const replay = await call(`/runs/${doc.id}/replay`);
		writeFileSync(`${out}/${key}.json`, JSON.stringify(replay));
		baked.push(key);
		console.log(
			key,
			`${((Date.now() - t0) / 1000).toFixed(0)}s`,
			`${(JSON.stringify(replay).length / 1e3).toFixed(0)} kB`,
		);
	}
	if (!wanted.length)
		writeFileSync(
			`${out}/index.json`,
			JSON.stringify({ wind: WIND, scenes: baked }),
		);
}
main();
