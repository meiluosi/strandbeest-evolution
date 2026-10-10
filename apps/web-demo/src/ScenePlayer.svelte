<script lang="ts">
import scenesFile from "../../../contracts/scenes.json";
import { call, runJob } from "./api";
import DiagnosisList from "./DiagnosisList.svelte";
import EnergyPanel from "./EnergyPanel.svelte";
import EventTimeline from "./EventTimeline.svelte";
import { currentDesign } from "./editor.svelte";
import Footfall from "./Footfall.svelte";
import { t } from "./i18n/index.svelte";
import ReplayViewport from "./ReplayViewport.svelte";
import { largestDifference, type Overlays, type Replay } from "./replay-types";
import { view } from "./store.svelte";

// shared with the agent tools (contracts/scenes.json)
const SCENES = scenesFile.scenes as Record<
	string,
	{ label: string; hint: string; sail?: boolean; ov: Record<string, any> }
>;

let key = $state("flat");
let wind = $state(3);
let busy = $state("");
let error = $state("");
let replay = $state<Replay | null>(null);
let label = $state("");
let previous = $state<{ replay: Replay; label: string } | null>(null);
let compare = $state(false);
let time = $state(0);
let playing = $state(true);
let speed = $state(1);
let follow = $state(true);
let overlays = $state<Overlays>({ forces: true, slip: true, com: true });

const scene = $derived(SCENES[key] as (typeof SCENES)[string]);
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

async function run() {
	busy = t("common.busy.simulating");
	error = "";
	try {
		const sc = scene;
		const ov: Record<string, any> = JSON.parse(JSON.stringify(sc.ov));
		ov.run = { settle: 0.5, revolutions: 2, frame_rate: 30, ...(ov.run ?? {}) };
		if (sc.sail) {
			ov.drive = { kind: "sail", ...(ov.drive ?? {}) };
			ov.wind = { ...(ov.wind ?? {}), speed: wind };
			ov.run = { ...ov.run, give_up_after: 6, max_time: 30 };
		}
		const doc = await runJob("/runs", {
			design: currentDesign(),
			ensemble: false,
			overrides: ov,
		});
		const next: Replay = await call(`/runs/${doc.id}/replay`);
		if (replay) previous = { replay, label };
		replay = next;
		label = `${t(sc.label)}${sc.sail ? ` · ${wind} m/s` : ""}`;
		time = 0;
		playing = true;
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	} finally {
		busy = "";
	}
}

// the one clock of the player: every viewport shows the frame nearest to `time`
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

const seek = (tt: number) => {
	playing = false;
	time = Math.max(0, Math.min(duration, tt));
};

// ---- synced charts (both runs when comparing) ----
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
const cursor = $derived(charts ? (time / charts.tmax) * 300 : 0);
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
		speed: dist / dur,
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

<div class="card">
	<h2>{t("scenes.title")}</h2>
	<p class="muted">{t("scenes.intro")}</p>
	<div class="chips">
		{#each Object.entries(SCENES) as [k, s]}
			<button class="btn small" class:primary={key === k} onclick={() => (key = k)} title={t(s.hint)}>{t(s.label)}</button>
		{/each}
	</div>
	<p class="muted">{t(scene.hint)}</p>
	<div class="row center">
		{#if scene.sail}<label>{t("scenes.meanWind")} <input type="number" min="0" max="20" step="0.5" bind:value={wind} /></label>{/if}
		<button class="btn primary" disabled={!!busy} onclick={run}>{t("scenes.run")}</button>
		{#if busy}<span class="muted"><span class="spin"></span>{busy}…</span>{/if}
		<small>{t("scenes.currentDesign", { name: view.name })}</small>
		{#if previous}<label class="inline"><input type="checkbox" bind:checked={compare} /> {t("compare.toggle", { label: previous.label })}</label>{/if}
	</div>
	{#if error}<p class="notice error">{t("common.error", { error: error })}</p>{/if}

	{#if runs.length}
		<div class="views" class:two={runs.length === 2}>
			{#each runs as r, i}
				<ReplayViewport replay={r} {time} {follow} {overlays} label={runs.length === 2 ? labels[i] : ""} highlight={!!diff && Math.abs(time - diff.t) < 0.1} />
			{/each}
		</div>
	{:else if !busy}
		<p class="muted">{t("scenes.noReplay")}</p>
	{/if}

	{#if replay && outcome && charts}
		<div class="row center">
			<button class="btn small" onclick={() => (playing = !playing)}>{playing ? t("common.pause") : t("common.play")}</button>
			<input type="range" min="0" max={duration} step={duration / 400 || 0.01} value={time} style="width:240px" oninput={(e) => seek(Number((e.target as HTMLInputElement).value))} />
			<small>{time.toFixed(2)} / {duration.toFixed(2)} s</small>
			<label class="inline">{t("scenes.speed")}
				<select bind:value={speed}><option value={0.25}>0.25×</option><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option></select>
			</label>
			<label class="inline"><input type="checkbox" bind:checked={follow} /> {t("scenes.follow")}</label>
		</div>
		<div class="row center layers">
			<b>{t("overlay.title")}</b>
			<label class="inline"><input type="checkbox" bind:checked={overlays.forces} /> {t("overlay.forces")}</label>
			<label class="inline"><input type="checkbox" bind:checked={overlays.slip} /> {t("overlay.slip")}</label>
			<label class="inline"><input type="checkbox" bind:checked={overlays.com} /> {t("overlay.com")}</label>
		</div>
		{#if diff}
			<p class="notice">{t("compare.largest", { time: diff.t.toFixed(2), mm: (diff.distance * 1000).toFixed(1) })} <button class="btn small" onclick={() => seek(diff.t)}>{t("compare.jump")}</button></p>
		{/if}
		{#if rows.length}
			<table class="cmp">
				<thead><tr><th></th><th>A</th><th>B</th><th>Δ</th></tr></thead>
				<tbody>
					{#each rows as r}
						<tr><td>{t(r.label)}</td><td>{r.a == null ? "–" : r.a.toFixed(r.digits)}</td><td>{r.b == null ? "–" : r.b.toFixed(r.digits)}</td><td>{r.a == null || r.b == null ? "–" : (r.b - r.a).toFixed(r.digits)}</td></tr>
					{/each}
				</tbody>
			</table>
		{/if}

		<div class="cards">
			<div class="stat"><b>{outcome.dist.toFixed(3)} m</b><span>{t("scenes.advancedIn", { dur: outcome.dur.toFixed(1) })}</span></div>
			<div class="stat"><b>{outcome.speed.toFixed(3)} m/s</b><span>{t("scenes.meanSpeed")}</span></div>
			{#if outcome.efficiency !== null}<div class="stat"><b>{(outcome.efficiency * 100).toFixed(0)}%</b><span>{t("scenes.efficiency")}</span></div>{/if}
			<div class="stat"><b>{replay.info.environment.gravity} m/s² · {replay.info.environment.air_density} kg/m³</b><span>{t("scenes.gravityDensity")}</span></div>
			<div class="stat"><b>{replay.info.drive === "sail" ? t("scenes.driveSail", { speed: replay.info.wind.speed }) : t("scenes.driveMotor")}</b><span>{t("scenes.drive", { gusts: replay.info.wind.kind === "gusts" ? t("scenes.gustsTag") : "" })}</span></div>
		</div>

		<DiagnosisList diagnosis={replay.diagnosis} />
		<h4>{t("timeline.title")}</h4>
		<EventTimeline {replay} {time} onseek={seek} />
		<h4>{t("footfall.title")}</h4>
		<Footfall {replay} {time} onseek={seek} />
		<EnergyPanel {replay} />

		<div class="plots">
			<div>
				<small>{t("scenes.chart.torque", { lo: charts.torque.lo.toFixed(4), hi: charts.torque.hi.toFixed(4) })}</small>
				<svg viewBox="0 0 300 50">{#each charts.torque.lines as l, i}<polyline points={l} fill="none" stroke={charts.torque.lines.length === 2 && i === 0 ? "var(--muted)" : "var(--accent)"} stroke-width="1.5" />{/each}<line x1={cursor} x2={cursor} y1="0" y2="50" stroke="var(--blue)" stroke-width="1" /></svg>
			</div>
			<div>
				<small>{t("scenes.chart.x", { lo: charts.x.lo.toFixed(3), hi: charts.x.hi.toFixed(3) })}</small>
				<svg viewBox="0 0 300 50">{#each charts.x.lines as l, i}<polyline points={l} fill="none" stroke={charts.x.lines.length === 2 && i === 0 ? "var(--muted)" : "var(--blue)"} stroke-width="1.5" />{/each}<line x1={cursor} x2={cursor} y1="0" y2="50" stroke="var(--accent)" stroke-width="1" /></svg>
			</div>
		</div>
		<small>{t("scenes.caveat")} {t("overlay.caveat")}</small>
	{/if}
</div>


<style>
	.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
	.views { display: grid; gap: 10px; margin: 8px 0; }
	.views.two { grid-template-columns: 1fr 1fr; }
	@media (max-width: 760px) { .views.two { grid-template-columns: 1fr; } }
	.plots { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; }
	.plots svg { width: 100%; height: 56px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); }
	input[type="number"] { width: 70px; }
	.cmp { border-collapse: collapse; font-size: 13px; margin: 6px 0; }
	.cmp td, .cmp th { padding: 3px 10px; border-bottom: 1px solid var(--line); text-align: right; }
	.cmp td:first-child { text-align: left; }
	h4 { margin: 12px 0 4px; }
	.layers { gap: 14px; }
</style>
