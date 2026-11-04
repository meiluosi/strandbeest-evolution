// Bake one replay per scene for the static (backend-free) web demo.
// Needs a running `strandbeest-api` (STRANDBEEST_API, default http://127.0.0.1:8000).
// Usage: tsx scripts/bake-gallery.ts [scene ...]   -> apps/web-demo/public/gallery/<scene>.json + index.json
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { defaultDesign } from "../packages/core/src";

const api = process.env.STRANDBEEST_API ?? "http://127.0.0.1:8000";
const out =
	process.env.STRANDBEEST_GALLERY_OUT ?? "apps/web-demo/public/gallery";
const scenes = JSON.parse(readFileSync("contracts/scenes.json", "utf8"))
	.scenes as Record<string, { sail?: boolean; ov: Record<string, any> }>;
const WIND = 3; // same default as the live scene player

const sha256 = (value: string | Buffer) =>
	createHash("sha256").update(value).digest("hex");

function sourceHashes() {
	const files = execFileSync(
		"git",
		[
			"ls-files",
			"--cached",
			"--others",
			"--exclude-standard",
			"--",
			"packages/sim/src",
			"packages/common/src",
			"apps/api/src",
			"packages/core/src",
			"crates/beest-kernel/src",
			"schemas",
			"contracts/scenes.json",
			"scripts/bake-gallery.ts",
		],
		{ encoding: "utf8" },
	)
		.trim()
		.split("\n");
	return Object.fromEntries(
		[...new Set(files)]
			.filter((p) => /\.(py|ts|rs|json)$/.test(p))
			.sort()
			.map((p) => [p, sha256(readFileSync(p))]),
	);
}

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
	const started = Date.now();
	const health = await call("/health");
	const manifest: Record<string, any> = {
		definition:
			"Mass-normalised contact damping (contact-v3), coherent t_n observations and discrete step work (energy-v2); original scene presets and physical defaults.",
		started_utc: new Date(started).toISOString(),
		git_head: execFileSync("git", ["rev-parse", "HEAD"], {
			encoding: "utf8",
		}).trim(),
		node: process.version,
		api_workers: health.workers,
		source_sha256: sourceHashes(),
		complete: false,
		scenes: {},
	};
	const checkpoint = () =>
		writeFileSync(
			`${out}/provenance.json`,
			`${JSON.stringify(manifest, null, "\t")}\n`,
		);
	checkpoint();
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
		if (
			replay.t?.[0] !== 0 ||
			replay.series?.t?.[0] !== 0 ||
			replay.energy?.t?.[0] !== 0
		)
			throw new Error(
				`${key}: replay is not aligned to the initial t_n boundary`,
			);
		if (!replay.scene?.geoms?.some((g: any) => g.name === "torso_geom"))
			throw new Error(
				`${key}: replay lacks the current torso geometry identity`,
			);
		for (const name of ["e_in", "e_contact", "e_loops", "e_friction"])
			if (replay.energy?.[name]?.[0] !== 0)
				throw new Error(`${key}: initial ${name} must be zero`);
		const serialized = JSON.stringify(replay);
		writeFileSync(`${out}/${key}.json`, serialized);
		manifest.scenes[key] = {
			run_id: doc.id,
			run_provenance: doc.provenance,
			scenario_sha256: sha256(JSON.stringify(doc.scenario)),
			overrides: ov,
			replay_sha256: sha256(serialized),
			bytes: Buffer.byteLength(serialized),
			wall_s: (Date.now() - t0) / 1000,
			validation: "t_n/zero initial work/current torso geometry checked",
		};
		checkpoint();
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
	const finalHashes = sourceHashes();
	manifest.sources_changed_during_bake = Object.keys(
		manifest.source_sha256,
	).filter((p) => manifest.source_sha256[p] !== finalHashes[p]);
	manifest.complete = manifest.sources_changed_during_bake.length === 0;
	manifest.wall_s = (Date.now() - started) / 1000;
	checkpoint();
	if (!manifest.complete)
		throw new Error(
			"source files changed during the bake; inspect provenance.json before using these replays",
		);
}
main().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
