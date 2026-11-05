<script lang="ts">
import { onDestroy, untrack } from "svelte";
import scenesFile from "../../../contracts/scenes.json";
import { call, type Job, runJob } from "./api";
import { type BrowserRun, simulateInBrowser } from "./browser-sim";
import DiagnosisList from "./DiagnosisList.svelte";
import EnergyPanel from "./EnergyPanel.svelte";
import EventTimeline from "./EventTimeline.svelte";
import EvidenceBadge from "./EvidenceBadge.svelte";
import { currentDesign } from "./editor.svelte";
import Footfall from "./Footfall.svelte";
import { t } from "./i18n/index.svelte";
import ReplayViewport from "./ReplayViewport.svelte";
import { largestDifference, type Overlays, type Replay } from "./replay-types";
import { recordCanvas, saveBlob, videoType } from "./share-export";
import { STATIC } from "./static";
import { store, view } from "./store.svelte";
import { fetchArrowTelemetry } from "./telemetry-arrow";

const SCENES = scenesFile.scenes as Record<
	string,
	{ label: string; hint: string; sail?: boolean; ov: Record<string, any> }
>;
type RunSource = "baked" | "browser" | "backend";
type RunStatus =
	| "idle"
	| "loading"
	| "running"
	| "ready"
	| "cancelled"
	| "error";
type PreviousRun = { replay: Replay; label: string };

let key = $state("flat");
let wind = $state(3);
let busy = $state("");
let error = $state("");
let status = $state<RunStatus>("idle");
let source = $state<RunSource | null>(null);
let replay = $state<Replay | null>(null);
let label = $state("");
let previous = $state<PreviousRun | null>(null);
let compare = $state(false);
let time = $state(0);
let playing = $state(false);
let speed = $state(1);
let follow = $state(true);
let overlays = $state<Overlays>({
	forces: true,
	slip: true,
	com: true,
	wind: true,
	trails: true,
	pvc: true,
	pneumatics: true,
});
let requestSerial = 0;
let cancelRequested = 0;
let bakedController: AbortController | null = null;
let backendJob = $state<Job | null>(null);

const scene = $derived(SCENES[key] as (typeof SCENES)[string]);
const running = $derived(status === "loading" || status === "running");
const runs = $derived(
	compare && previous && replay
		? [previous.replay, replay]
		: replay
			? [replay]
			: [],
);
const duration = $derived(
	Math.max(0, ...runs.map((r) => r.t.at(-1) as number)),
);
const labels = $derived(
	compare && previous ? [`A · ${previous.label}`, `B · ${label}`] : [label],
);
const diff = $derived(
	compare && previous && replay
		? largestDifference(previous.replay, replay)
		: null,
);
const sourceLabel = $derived(
	source === "baked"
		? t("scenes.source.baked")
		: source === "browser"
			? t("scenes.source.browser")
			: source === "backend"
				? t("scenes.source.backend")
				: "",
);
const statusLabel = $derived.by(() => {
	switch (status) {
		case "loading":
			return t("scenes.status.loading");
		case "running":
			return t("scenes.status.running");
		case "ready":
			return t("scenes.status.ready");
		case "cancelled":
			return t("scenes.status.cancelled");
		case "error":
			return t("scenes.status.error");
		default:
			return t("scenes.status.idle");
	}
});

const LAYERS = [
	{ id: "forces", label: "overlay.forces" },
	{ id: "slip", label: "overlay.slip" },
	{ id: "com", label: "overlay.com" },
	{ id: "wind", label: "overlay.wind" },
	{ id: "trails", label: "overlay.trails" },
	{ id: "pvc", label: "overlay.pvc" },
	{ id: "pneumatics", label: "overlay.pneumatics" },
] as const;
const availability = $derived.by(() => {
	const every = (has: (r: Replay) => boolean) =>
		runs.length > 0 && runs.every(has);
	return {
		forces: every((r) => !!r.foot_force?.length && !!r.foot_pos?.length),
		slip: every((r) => !!r.foot_slip?.length),
		com: every(
			(r) => !!r.com?.length && !!r.foot_pos?.length && !!r.contact.length,
		),
		wind: every((r) => r.info.drive === "sail" && r.info.wind.speed > 0.05),
		trails: every((r) => !!r.foot_pos?.length && !!r.contact.length),
		pvc: every((r) => r.scene.geoms.length > 0),
		pneumatics: every((r) => !!r.pneumatics || !!r.info.pneumatics),
	};
});
const effectiveOverlays = $derived({
	forces: overlays.forces && availability.forces,
	slip: overlays.slip && availability.slip,
	com: overlays.com && availability.com,
	wind: overlays.wind && availability.wind,
	trails: overlays.trails && availability.trails,
	pvc: overlays.pvc && availability.pvc,
	pneumatics: overlays.pneumatics && availability.pneumatics,
});

function beginRequest(): PreviousRun | null {
	requestSerial += 1;
	cancelRequested = 0;
	bakedController?.abort();
	browserRun?.cancel();
	if (backendJob)
		void call(`/jobs/${backendJob.id}/cancel`, {}).catch(() => {});
	const prior = replay && label ? { replay, label } : null;
	replay = null;
	label = "";
	previous = null;
	compare = false;
	source = null;
	time = 0;
	playing = false;
	progress = null;
	backendJob = null;
	error = "";
	return prior;
}

function finishRequest(
	id: number,
	next: Replay,
	nextLabel: string,
	nextSource: RunSource,
	prior: PreviousRun | null,
): boolean {
	if (id !== requestSerial) return false;
	previous = prior;
	replay = next;
	label = nextLabel;
	source = nextSource;
	status = "ready";
	time = 0;
	playing = true;
	return true;
}

async function loadBaked(k: string) {
	const prior = beginRequest();
	const id = requestSerial;
	const controller = new AbortController();
	bakedController = controller;
	status = "loading";
	busy = t("scenes.loading");
	try {
		const response = await fetch(`./gallery/${k}.json`, {
			signal: controller.signal,
		});
		if (!response.ok) throw new Error(`${response.status} ${k}`);
		const next: Replay = await response.json();
		finishRequest(id, next, t(SCENES[k]?.label ?? k), "baked", prior);
	} catch (e) {
		if (id !== requestSerial) return;
		status = cancelRequested === id ? "cancelled" : "error";
		if (cancelRequested !== id)
			error = e instanceof Error ? e.message : String(e);
	} finally {
		if (id === requestSerial) {
			busy = "";
			bakedController = null;
		}
	}
}
$effect(() => {
	if (!STATIC) return;
	const requestedKey = key;
	untrack(() => loadBaked(requestedKey));
});

function selectScene(next: string) {
	if (next !== key) {
		key = next;
	} else if (STATIC && !running) {
		void loadBaked(next);
	}
}

let revs = $state(1);
let browserRun = $state<BrowserRun | null>(null);
let progress = $state<{ phase: string; fraction: number } | null>(null);
let tabHiddenDuringSim = $state(false);

$effect(() => {
	if (typeof document === "undefined") return;
	const onVis = () => {
		if (document.hidden && browserRun) tabHiddenDuringSim = true;
	};
	document.addEventListener("visibilitychange", onVis);
	return () => document.removeEventListener("visibilitychange", onVis);
});

async function simulateHere() {
	if (running) return;
	const sceneKey = key;
	const sceneSnapshot = scene;
	const windSnapshot = wind;
	const prior = beginRequest();
	const id = requestSerial;
	status = "running";
	tabHiddenDuringSim = false;
	const run = simulateInBrowser(
		currentDesign(),
		sceneKey,
		revs,
		windSnapshot,
		(p) => {
			if (id === requestSerial) progress = p;
		},
	);
	browserRun = run;
	try {
		const { replay: next } = await run.promise;
		finishRequest(
			id,
			next as unknown as Replay,
			`${t(sceneSnapshot.label)}${sceneSnapshot.sail ? ` · ${windSnapshot} m/s` : ""} · ${t("scenes.browserTag")}`,
			"browser",
			prior,
		);
	} catch (e) {
		if (id !== requestSerial) return;
		status = cancelRequested === id ? "cancelled" : "error";
		const msg = e instanceof Error ? e.message : String(e);
		if (cancelRequested !== id && msg !== "cancelled") error = msg;
	} finally {
		if (id === requestSerial) {
			browserRun = null;
			progress = null;
		}
	}
}

async function run() {
	if (running) return;
	const sceneSnapshot = scene;
	const windSnapshot = wind;
	const prior = beginRequest();
	const id = requestSerial;
	status = "running";
	busy = t("common.busy.simulating");
	try {
		const ov: Record<string, any> = JSON.parse(
			JSON.stringify(sceneSnapshot.ov),
		);
		ov.run = {
			...(ov.run ?? {}),
			settle: 0.5,
			revolutions: revs,
			frame_rate: 30,
		};
		if (sceneSnapshot.sail) {
			ov.drive = { kind: "sail", ...(ov.drive ?? {}) };
			ov.wind = { ...(ov.wind ?? {}), speed: windSnapshot };
			ov.run = { ...ov.run, give_up_after: 6, max_time: 30 };
		}
		const doc = await runJob(
			"/runs",
			{
				design: currentDesign(),
				ensemble: false,
				overrides: ov,
			},
			(j) => {
				if (id === requestSerial) backendJob = j;
			},
		);
		if (id !== requestSerial) return;
		let next: Replay;
		try {
			const decoded = await fetchArrowTelemetry(doc.id, undefined, store.api);
			next = decoded.toReplay();
		} catch {
			next = await call(`/runs/${doc.id}/replay`);
		}
		finishRequest(
			id,
			next,
			`${t(sceneSnapshot.label)}${sceneSnapshot.sail ? ` · ${windSnapshot} m/s` : ""}`,
			"backend",
			prior,
		);
	} catch (e) {
		if (id !== requestSerial) return;
		status = cancelRequested === id ? "cancelled" : "error";
		if (cancelRequested !== id)
			error = e instanceof Error ? e.message : String(e);
	} finally {
		if (id === requestSerial) {
			busy = "";
			backendJob = null;
		}
	}
}

function cancelActive() {
	if (!running) return;
	cancelRequested = requestSerial;
	status = "cancelled";
	busy = "";
	bakedController?.abort();
	browserRun?.cancel();
	if (backendJob)
		void call(`/jobs/${backendJob.id}/cancel`, {}).catch(() => {});
	progress = null;
}

onDestroy(() => {
	requestSerial += 1;
	bakedController?.abort();
	browserRun?.cancel();
	if (backendJob)
		void call(`/jobs/${backendJob.id}/cancel`, {}).catch(() => {});
});

$effect(() => {
	let raf = 0;
	let last = performance.now();
	const tick = (now: number) => {
		raf = requestAnimationFrame(tick);
		if (playing && duration > 0) {
			time += ((now - last) / 1000) * speed;
			if (time > duration) time = 0;
		}
		last = now;
	};
	raf = requestAnimationFrame(tick);
	return () => cancelAnimationFrame(raf);
});

let recording = $state(false);
async function record() {
	const canvas = document.querySelector<HTMLCanvasElement>(".views canvas");
	if (!canvas || recording) return;
	error = "";
	try {
		const stop = recordCanvas(canvas);
		recording = true;
		compare = false;
		time = 0;
		speed = 1;
		playing = true;
		let prev = 0;
		await new Promise<void>((done) => {
			const poll = () => {
				if (time < prev) return done();
				prev = time;
				requestAnimationFrame(poll);
			};
			requestAnimationFrame(poll);
		});
		const { blob, ext } = await stop();
		saveBlob(`strandbeest-${key}.${ext}`, blob);
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	} finally {
		recording = false;
	}
}

const seek = (tt: number) => {
	playing = false;
	time = Math.max(0, Math.min(duration, tt));
};

function line(
	xs: number[],
	ys: number[],
	lo: number,
	hi: number,
	tmax: number,
): string {
	return ys
		.map(
			(y, i) =>
				`${((xs[i] as number) / tmax) * 300},${46 - ((y - lo) / (hi - lo || 1)) * 40}`,
		)
		.join(" ");
}
const charts = $derived.by(() => {
	if (!runs.length) return null;
	const tmax = Math.max(...runs.map((r) => Math.max(...r.series.t)));
	const mk = (key: "torque" | "x") => {
		const all = runs.flatMap((r) => r.series[key]);
		const lo = Math.min(...all);
		const hi = Math.max(...all);
		return {
			lo,
			hi,
			lines: runs.map((r) => line(r.series.t, r.series[key], lo, hi, tmax)),
		};
	};
	return { tmax, torque: mk("torque"), x: mk("x") };
});
const cursor = $derived(charts?.tmax ? (time / charts.tmax) * 300 : 0);
const outcome = $derived.by(() => {
	if (!replay) return null;
	const dist =
		(replay.series.x.at(-1) as number) - (replay.series.x[0] as number);
	const dur = replay.series.t.at(-1) as number;
	const ideal = replay.nominal_stride_m
		? replay.nominal_stride_m * replay.revolutions
		: null;
	return {
		dist,
		dur,
		speed: dur > 0 ? dist / dur : 0,
		efficiency: ideal ? dist / ideal : null,
	};
});
const METRICS = [
	{ id: "stride_per_rev", label: "compare.stride", digits: 4 },
	{ id: "mean_speed", label: "compare.speed", digits: 4 },
	{ id: "mean_torque", label: "compare.meanTorque", digits: 5 },
	{ id: "peak_torque", label: "compare.peakTorque", digits: 4 },
	{ id: "energy_in_per_rev", label: "compare.energy", digits: 5 },
] as const;
const rows = $derived(
	compare && previous && replay
		? METRICS.map((m) => ({
				...m,
				a: previous?.replay.metrics[m.id] as number | null,
				b: replay?.metrics[m.id] as number | null,
			}))
		: [],
);
</script>

<section class="scene-player card" aria-label={t("scenes.title")}>
	<div class="player-heading">
		<div>
			<span class="eyebrow">{t("scenes.playerEyebrow")}</span>
			<h2>{t("scenes.title")}</h2>
			<p class="muted">{t("scenes.intro")}</p>
		</div>
		<div class="run-provenance">
			{#if source}<span class="source-badge">{sourceLabel}</span>{/if}
			{#if replay}<EvidenceBadge evidence={(replay as any).evidence} />{/if}
		</div>
	</div>

	<div class="player-layout">
		<aside class="scene-config">
			<span class="section-label">{t("scenes.configuration")}</span>
			<div class="chips" aria-label={t("scenes.configuration")}>
				{#each Object.entries(SCENES) as [k, s]}
					<button class="btn small" class:primary={key === k} disabled={running} onclick={() => selectScene(k)} title={t(s.hint)}>{t(s.label)}</button>
				{/each}
			</div>
			<p class="scene-hint">{t(scene.hint)}</p>
			<div class="run-controls">
				{#if scene.sail}<label>{t("scenes.meanWind")} <input type="number" min="0" max="20" step="0.5" bind:value={wind} disabled={running} /></label>{/if}
				<label>{t("scenes.revs")} <select bind:value={revs} disabled={running}><option value={1}>1</option><option value={2}>2</option></select></label>
				{#if !STATIC}<button class="btn primary" disabled={running} onclick={run}>{t("scenes.run")}</button>{/if}
				<button class="btn" class:primary={STATIC} disabled={running} onclick={simulateHere}>{t("scenes.browserRun")}</button>
				{#if running}<button class="btn" onclick={cancelActive}>{t("common.cancel")}</button>{/if}
			</div>
			<small class="design-context">{STATIC ? t("scenes.recorded") : t("scenes.currentDesign", { name: view.name })}</small>
			{#if previous}<label class="inline compare-toggle"><input type="checkbox" bind:checked={compare} /> {t("compare.toggle", { label: previous.label })}</label>{/if}
		</aside>

		<div class="replay-stage">
			<div class="stage-status" role="status">
				<span class="status-dot {status}"></span>
				<strong>{statusLabel}</strong>
				{#if browserRun}<span>{progress?.phase === "load" ? t("scenes.browserLoading") : t("scenes.browserRunning", { pct: Math.round((progress?.fraction ?? 0) * 100) })}</span>{:else if busy}<span>{busy}…{#if backendJob?.progress.total} {backendJob.progress.done}/{backendJob.progress.total}{/if}</span>{/if}
			</div>
			{#if tabHiddenDuringSim && browserRun}<p class="notice warning">{t("scenes.browserBackgroundWarning")}</p>{/if}
			{#if status === "cancelled"}<p class="notice info">{t("scenes.cancelled")}</p>{/if}
			{#if error}<p class="notice error" role="alert">{t("common.error", { error })}</p>{/if}

			{#if runs.length}
				<div class="views" class:two={runs.length === 2}>
					{#each runs as r, i}
						<ReplayViewport replay={r} {time} {follow} overlays={effectiveOverlays} label={labels[i]} highlight={!!diff && Math.abs(time - diff.t) < 0.1} />
					{/each}
				</div>
			{:else}
				<div class="empty-replay">
					<strong>{running ? busy || t("scenes.loading") : t("scenes.noReplayTitle")}</strong>
					<p>{running ? t("scenes.loadingCurrent") : t("scenes.noReplay")}</p>
				</div>
			{/if}

			{#if replay && outcome && charts}
				<div class="playback-bar">
					<button class="btn small" onclick={() => (playing = !playing)}>{playing ? t("common.pause") : t("common.play")}</button>
					<input aria-label={t("scenes.timeline")} type="range" min="0" max={duration} step="any" value={time} oninput={(e) => seek(Number((e.target as HTMLInputElement).value))} />
					<output>{time.toFixed(2)} / {duration.toFixed(2)} s</output>
					<label class="inline">{t("scenes.speed")}
						<select bind:value={speed}><option value={0.25}>0.25×</option><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option></select>
					</label>
					<label class="inline"><input type="checkbox" bind:checked={follow} /> {t("scenes.follow")}</label>
				</div>
				<div class="layers">
					<span class="section-label">{t("overlay.title")}</span>
					<div class="layer-options">
						{#each LAYERS as layer}
							<label class="inline" class:unavailable={!availability[layer.id]} title={availability[layer.id] ? "" : t("overlay.unavailable")}>
								<input type="checkbox" checked={effectiveOverlays[layer.id]} disabled={!availability[layer.id]} onchange={(e) => (overlays[layer.id] = (e.target as HTMLInputElement).checked)} /> {t(layer.label)}
							</label>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	</div>

	{#if replay && outcome && charts}
		<div class="run-analysis">
			{#if replay.stalled}<p class="notice error">{t("scenes.stalledNotice")}</p>{/if}
			{#if diff}<p class="notice">{t("compare.largest", { time: diff.t.toFixed(2), mm: (diff.distance * 1000).toFixed(1) })} <button class="btn small" onclick={() => seek(diff.t)}>{t("compare.jump")}</button></p>{/if}
			{#if rows.length}
				<table class="cmp" aria-label={t("compare.title")}>
					<caption>{t("compare.title")}</caption>
					<thead><tr><th>{t("compare.metric")}</th><th title={previous?.label}>A</th><th title={label}>B</th><th>{t("compare.delta")}</th></tr></thead>
					<tbody>
						{#each rows as r}
							<tr><td>{t(r.label)}</td><td>{r.a == null ? "–" : r.a.toFixed(r.digits)}</td><td>{r.b == null ? "–" : r.b.toFixed(r.digits)}</td><td>{r.a == null || r.b == null ? "–" : (r.b - r.a).toFixed(r.digits)}</td></tr>
						{/each}
					</tbody>
				</table>
			{/if}

			{#if source === "browser"}<p class="notice">{t("scenes.browserNotice")}</p>{/if}
			<p class="summary">{replay.stalled ? t("scenes.summaryStalled", { scene: label, dur: outcome.dur.toFixed(1) }) : t(outcome.efficiency === null ? "scenes.summary" : "scenes.summaryEff", { scene: label, dist: outcome.dist.toFixed(2), dur: outcome.dur.toFixed(1), speed: outcome.speed.toFixed(3), eff: Math.round((outcome.efficiency ?? 0) * 100) })}</p>
			<div class="result-actions">
				{#if videoType()}<button class="btn small" disabled={recording} onclick={record}>{recording ? t("scenes.recording") : t("scenes.record")}</button>{/if}
				<small>{sourceLabel} · {label}</small>
			</div>
			<div class="cards result-metrics">
				<div class="stat"><b>{outcome.dist.toFixed(3)} m</b><span>{t("scenes.advancedIn", { dur: outcome.dur.toFixed(1) })}</span></div>
				<div class="stat"><b>{outcome.speed.toFixed(3)} m/s</b><span>{t("scenes.meanSpeed")}</span></div>
				{#if outcome.efficiency !== null}<div class="stat"><b>{(outcome.efficiency * 100).toFixed(0)}%</b><span>{t("scenes.efficiency")}</span></div>{/if}
				<div class="stat"><b>{replay.info.environment.gravity} m/s² · {replay.info.environment.air_density} kg/m³</b><span>{t("scenes.gravityDensity")}</span></div>
				<div class="stat"><b>{replay.info.drive === "sail" ? t("scenes.driveSail", { speed: replay.info.wind.speed }) : t("scenes.driveMotor")}</b><span>{t("scenes.drive", { gusts: replay.info.wind.kind === "gusts" ? t("scenes.gustsTag") : "" })}</span></div>
			</div>

			<DiagnosisList diagnosis={replay.diagnosis} />
			<section class="time-analysis">
				<div class="analysis-heading"><h3>{t("timeline.title")}</h3><span>{time.toFixed(2)} s</span></div>
				<EventTimeline {replay} {time} onseek={seek} />
				<h3>{t("footfall.title")}</h3>
				<Footfall {replay} {time} onseek={seek} />
				<EnergyPanel {replay} />
				<div class="plots">
					<div>
						<small>{t("scenes.chart.torque", { lo: charts.torque.lo.toFixed(4), hi: charts.torque.hi.toFixed(4) })}</small>
						<svg viewBox="0 0 300 50" role="img" aria-label={t("scenes.chart.torque", { lo: charts.torque.lo.toFixed(4), hi: charts.torque.hi.toFixed(4) })}>{#each charts.torque.lines as l, i}<polyline points={l} fill="none" stroke={charts.torque.lines.length === 2 && i === 0 ? "var(--muted)" : "var(--accent)"} stroke-width="1.5" />{/each}<line class="time-cursor" x1={cursor} x2={cursor} y1="0" y2="50" stroke="var(--blue)" stroke-width="1" /></svg>
					</div>
					<div>
						<small>{t("scenes.chart.x", { lo: charts.x.lo.toFixed(3), hi: charts.x.hi.toFixed(3) })}</small>
						<svg viewBox="0 0 300 50" role="img" aria-label={t("scenes.chart.x", { lo: charts.x.lo.toFixed(3), hi: charts.x.hi.toFixed(3) })}>{#each charts.x.lines as l, i}<polyline points={l} fill="none" stroke={charts.x.lines.length === 2 && i === 0 ? "var(--muted)" : "var(--blue)"} stroke-width="1.5" />{/each}<line class="time-cursor" x1={cursor} x2={cursor} y1="0" y2="50" stroke="var(--accent)" stroke-width="1" /></svg>
					</div>
				</div>
			</section>
			<details class="limitations">
				<summary>{t("scenes.limitations")}</summary>
				<p>{t("scenes.caveat")} {t("overlay.caveat")}</p>
				<p>{t("scenes.sourceLimits")}</p>
			</details>
		</div>
	{/if}
</section>

<style>
	.scene-player { min-width: 0; padding: 22px; }
	.player-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
	.player-heading h2 { margin: 4px 0 0; font-size: 22px; letter-spacing: -0.025em; }
	.player-heading p { max-width: 760px; margin: 6px 0 0; }
	.eyebrow, .section-label { color: var(--accent-strong); font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: 0.11em; }
	.run-provenance { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 7px; }
	.source-badge { padding: 4px 8px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface-muted); color: var(--text-soft); font-size: 11px; white-space: nowrap; }
	.player-layout { display: grid; grid-template-columns: 238px minmax(0, 1fr); gap: 20px; margin-top: 20px; }
	.scene-config { min-width: 0; padding-right: 20px; border-right: 1px solid var(--line); }
	.chips { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin: 10px 0; }
	.chips .btn { justify-content: flex-start; min-width: 0; padding-inline: 8px; }
	.scene-hint { min-height: 48px; color: var(--text-muted); font-size: 12px; line-height: 1.55; }
	.run-controls { display: grid; gap: 9px; align-items: center; }
	.run-controls label { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 12px; }
	.run-controls .btn { width: 100%; }
	input[type="number"] { width: 70px; }
	.design-context { display: block; margin-top: 12px; color: var(--text-muted); line-height: 1.55; }
	.compare-toggle { align-items: flex-start; margin-top: 12px; line-height: 1.45; }
	.replay-stage { min-width: 0; }
	.stage-status { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; min-height: 26px; margin-bottom: 8px; color: var(--text-muted); font-size: 12px; }
	.stage-status strong { color: var(--text-soft); font-weight: 600; }
	.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-muted); }
	.status-dot.loading, .status-dot.running { background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
	.status-dot.ready { background: var(--success); }
	.status-dot.error { background: var(--bad); }
	.views { display: grid; gap: 10px; }
	.views.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
	.empty-replay { min-height: 280px; display: grid; place-content: center; padding: 28px; border: 1px dashed var(--line); border-radius: 10px; background: var(--surface-muted); text-align: center; }
	.empty-replay strong { font-size: 14px; }
	.empty-replay p { margin: 6px 0 0; color: var(--text-muted); font-size: 12px; }
	.playback-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin-top: 12px; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-muted); }
	.playback-bar input[type="range"] { flex: 1 1 180px; min-width: 120px; }
	.playback-bar output { min-width: 100px; font-family: var(--font-mono); font-size: 11px; text-align: center; }
	.layers { margin-top: 12px; }
	.layer-options { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 7px; }
	.layer-options label { font-size: 12px; }
	.layer-options .unavailable { opacity: 0.48; cursor: not-allowed; }
	.run-analysis { margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--line); }
	.summary { margin: 10px 0 4px; font-size: 15px; }
	.result-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 8px 0; }
	.result-actions small { min-width: 0; overflow: hidden; color: var(--text-muted); text-overflow: ellipsis; white-space: nowrap; }
	.result-metrics { margin: 12px 0; }
	.cmp { width: 100%; margin: 10px 0 16px; border-collapse: collapse; font-size: 13px; }
	.cmp caption { margin-bottom: 6px; color: var(--text-soft); font-weight: 600; text-align: left; }
	.cmp td, .cmp th { padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: right; }
	.cmp td:first-child, .cmp th:first-child { text-align: left; }
	.time-analysis { margin-top: 18px; }
	.time-analysis h3 { margin: 16px 0 7px; font-size: 14px; }
	.analysis-heading { display: flex; align-items: baseline; justify-content: space-between; }
	.analysis-heading span { color: var(--accent-strong); font-family: var(--font-mono); font-size: 12px; }
	.plots { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
	.plots svg { width: 100%; height: 76px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); }
	.limitations { margin-top: 16px; color: var(--text-muted); font-size: 12px; line-height: 1.6; }
	@media (max-width: 1050px) {
		.player-layout { grid-template-columns: minmax(0, 1fr); }
		.scene-config { padding: 0 0 18px; border-right: 0; border-bottom: 1px solid var(--line); }
		.chips { grid-template-columns: repeat(5, minmax(0, 1fr)); }
		.scene-hint { min-height: 0; }
		.run-controls { display: flex; flex-wrap: wrap; }
		.run-controls .btn { width: auto; }
	}
	@media (max-width: 760px) {
		.views.two, .plots { grid-template-columns: minmax(0, 1fr); }
		.chips { grid-template-columns: repeat(2, minmax(0, 1fr)); }
		.player-heading { flex-direction: column; gap: 10px; }
		.run-provenance { justify-content: flex-start; }
	}
	@media (max-width: 480px) {
		.scene-player { padding: 14px; }
		.player-layout { gap: 14px; margin-top: 14px; }
		.run-controls { display: grid; }
		.run-controls .btn { width: 100%; }
		.playback-bar output { min-width: 0; }
		.result-actions { align-items: flex-start; flex-direction: column; }
		.result-actions small { width: 100%; white-space: normal; }
		.cmp { font-size: 11px; }
		.cmp td, .cmp th { padding: 6px 4px; }
	}
</style>
