<script lang="ts">
import { newUlid } from "strandbeest-core";
import { call, runJob } from "./api";
import { t } from "./i18n/index.svelte";
import { currentDesign, store } from "./store.svelte";

type Meas = {
	id: string;
	name: string;
	design_id: string;
	design_name?: string;
	synthetic: boolean;
	conditions: { kind: string };
};
type Cmp = {
	angle_deg: number[];
	measured: (number | null)[];
	simulated: (number | null)[];
	stride_measured: number | null;
	stride_simulated: number | null;
	distance: number | null;
};
type Profile = {
	name: string;
	parameters: Record<string, number>;
	provenance: { residual: number; method: string; synthetic?: boolean };
};

let busy = $state("");
let error = $state("");
let info = $state("");
let measurements = $state<Meas[]>([]);
let runs = $state<{ id: string; design_id: string; design_name: string }[]>([]);
let mId = $state("");
let runId = $state("");
let cmp = $state<Cmp | null>(null);
let profile = $state<Profile | null>(null);
let calParams = $state({ contact_stiffness: true, friction: false });

// import form
let newName = $state("bench-1");
let kind = $state("motor_no_wind");
let omega = $state(2.0);
let wind = $state(0);
let synthetic = $state(false);
let channels = $state<Record<string, number[]> | null>(null);
let fileName = $state("");
// ---- raw rig data ----
type Quality = {
	sample_rate_hz: number;
	duration_s: number;
	revolutions: number;
	speed_mean_rad_s: number;
	speed_cv: number;
	dropouts: number;
	time_offset_s: number | null;
	warnings: string[];
};
let rawText = $state("");
let rawName = $state("");
let trackText = $state("");
let cal = $state({
	counts_per_motor_rev: 48,
	gear_ratio: 100,
	direction: 1,
	torque_method: "current",
	kt_nm_per_a: 0.5,
	idle_current_ma: 0,
	calibrated: false,
});
let surface = $state("");
let converted = $state<{ doc: any; q: Quality } | null>(null);

async function readText(
	e: Event,
): Promise<{ name: string; text: string } | null> {
	const f = (e.target as HTMLInputElement).files?.[0];
	return f ? { name: f.name, text: await f.text() } : null;
}
const pickRaw = async (e: Event) => {
	const r = await readText(e);
	if (r) {
		rawText = r.text;
		rawName = r.name;
		converted = null;
	}
};
const pickTrack = async (e: Event) => {
	const r = await readText(e);
	if (r) trackText = r.text;
};
const pickCal = async (e: Event) => {
	const r = await readText(e);
	if (r) cal = { ...cal, ...JSON.parse(r.text) };
};
const convertRaw = () =>
	guard(t("lab.busy.converting"), async () => {
		const doc = await call("/rig/convert", {
			raw_csv: rawText,
			raw_name: rawName,
			calibration: cal,
			name: newName,
			design_id: store.designId,
			design_name: store.name,
			kind,
			omega,
			wind: kind === "fan" ? wind : undefined,
			surface,
			track_csv: trackText || undefined,
		});
		converted = { doc, q: doc.quality };
	});
const saveConverted = () =>
	guard(t("common.save"), async () => {
		if (!converted) return;
		await call("/measurements", converted.doc);
		measurements = await call("/measurements");
		mId = converted.doc.id;
		info = t("lab.savedFromRig", { name: converted.doc.name });
	});
const timeSeries = $derived.by(() => {
	if (!converted) return null;
	const ch = converted.doc.channels;
	const tq: number[] | undefined = ch.torque;
	if (!tq) return null;
	const lo = Math.min(...tq);
	const hi = Math.max(...tq);
	const t: number[] = ch.t;
	const stride = Math.max(1, Math.floor(tq.length / 400));
	const pts = tq
		.filter((_, i) => i % stride === 0)
		.map(
			(y, i) =>
				`${((t[i * stride] as number) / (t.at(-1) as number)) * 300},${95 - ((y - lo) / (hi - lo || 1)) * 85}`,
		);
	return { pts: pts.join(" "), lo, hi };
});

async function guard(label: string, fn: () => Promise<void>) {
	busy = label;
	error = "";
	info = "";
	try {
		await fn();
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	} finally {
		busy = "";
	}
}

const refresh = () =>
	guard(t("lab.busy.reading"), async () => {
		measurements = await call("/measurements");
		runs = await call("/runs");
	});

function parseCsv(text: string): Record<string, number[]> {
	const lines = text.trim().split(/\r?\n/);
	const head = (lines[0] ?? "").split(",").map((h) => h.trim());
	const out: Record<string, number[]> = Object.fromEntries(
		head.map((h) => [h, []]),
	);
	for (const line of lines.slice(1)) {
		line.split(",").forEach((v, i) => {
			const n = Number(v);
			if (!Number.isFinite(n))
				throw new Error(t("lab.csv.nonNumeric", { v: v }));
			(out[head[i] as string] as number[]).push(n);
		});
	}
	return out;
}

async function pick(e: Event) {
	const f = (e.target as HTMLInputElement).files?.[0];
	if (!f) return;
	await guard(t("lab.busy.parsing"), async () => {
		const text = await f.text();
		fileName = f.name;
		if (f.name.endsWith(".json")) {
			const doc = JSON.parse(text);
			channels = doc.channels ?? doc;
			newName = doc.name ?? doc.id ?? newName;
		} else channels = parseCsv(text);
		if (!channels?.t) throw new Error(t("lab.csv.needColumns"));
		info = t("lab.csv.read", {
			join: Object.keys(channels).join(", "),
			n: channels.t.length,
		});
	});
}

const save = () =>
	guard(t("common.save"), async () => {
		if (!channels) throw new Error(t("lab.pickFile"));
		const saved = await call("/measurements", {
			schema_version: 2,
			id: newUlid(),
			name: newName,
			design_id: store.designId,
			design_name: store.name,
			synthetic,
			conditions: {
				kind,
				omega_rad_s: omega,
				...(kind === "fan" ? { wind_m_s: wind } : {}),
			},
			channels,
		});
		measurements = await call("/measurements");
		mId = saved.id;
		info = t("lab.saved", { newName: newName });
	});

const compare = () =>
	guard(t("lab.busy.comparing"), async () => {
		cmp = await call("/compare", { measurement: mId, run_id: runId });
	});

const calibrate = () =>
	guard(t("lab.busy.calibrating"), async () => {
		const names = Object.entries(calParams)
			.filter(([, on]) => on)
			.map(([n]) => n);
		profile = await runJob("/calibrations", {
			design: currentDesign(),
			measurement: mId,
			params: names,
			max_evals: 20,
		});
	});

const chart = $derived.by(() => {
	if (!cmp) return null;
	const all = [...cmp.measured, ...cmp.simulated].filter(
		(v): v is number => v !== null,
	);
	const lo = Math.min(...all);
	const hi = Math.max(...all);
	const line = (a: (number | null)[]) =>
		a
			.map((y, i) =>
				y === null
					? null
					: `${((cmp?.angle_deg[i] as number) / 360) * 300},${95 - ((y - lo) / (hi - lo || 1)) * 85}`,
			)
			.filter(Boolean)
			.join(" ");
	return { m: line(cmp.measured), s: line(cmp.simulated), lo, hi };
});
</script>

<div class="stack">
	<div class="card">
		<h2>{t("lab.title")}</h2>
		<p class="muted">{t("lab.intro")}</p>
		<div class="row center"><button class="btn" disabled={!!busy} onclick={refresh}>{t("lab.refresh")}</button>{#if busy}<span class="muted"><span class="spin"></span>{busy}…</span>{/if}</div>
		{#if error}<p class="notice error">{t("common.error", { error: error })}</p>{/if}
		{#if info}<p class="notice info">{info}</p>{/if}
	</div>

	<div class="card">
		<h3>{t("lab.raw.title")}</h3>
		<p class="muted">{t("lab.raw.intro.before")}<code>t_ms,enc,current_mA,…</code>{t("lab.raw.intro.middle")} <code>hardware/README.md</code>{t("common.period")}</p>
		<div class="row">
			<label class="btn inline" style="cursor:pointer">{t("lab.raw.csv")} <input type="file" accept=".csv,.txt" onchange={pickRaw} hidden /></label>
			<label class="btn inline" style="cursor:pointer">{t("lab.raw.trackCsv")} <input type="file" accept=".csv" onchange={pickTrack} hidden /></label>
			<label class="btn inline" style="cursor:pointer">{t("lab.raw.importCal")} <input type="file" accept=".json" onchange={pickCal} hidden /></label>
			<small>{rawName ? t("lab.raw.picked", { rawName: rawName }) : t("lab.raw.none")}{trackText ? t("lab.raw.trackPicked") : ""}</small>
		</div>
		<div class="row">
			<label>{t("lab.cal.countsPerRev")} <input type="number" step="1" bind:value={cal.counts_per_motor_rev} /></label>
			<label>{t("lab.cal.gearRatio")} <input type="number" step="1" bind:value={cal.gear_ratio} /></label>
			<label>{t("lab.cal.direction")}
				<select bind:value={cal.direction}><option value={1}>+1</option><option value={-1}>-1</option></select>
			</label>
			<label>{t("lab.cal.torqueConstant")} <input type="number" step="0.01" bind:value={cal.kt_nm_per_a} /></label>
			<label>{t("lab.cal.noLoadCurrent")} <input type="number" step="1" bind:value={cal.idle_current_ma} /></label>
			<label>{t("lab.cal.surface")} <input type="text" bind:value={surface} size="10" placeholder="glass" /></label>
			<label class="inline"><input type="checkbox" bind:checked={cal.calibrated} /> {t("lab.cal.verified")}</label>
		</div>
		<div class="row center">
			<small>{t("lab.cal.sharedNote")}</small>
			<button class="btn primary" disabled={!!busy || !rawText} onclick={convertRaw}>{t("lab.raw.convert")}</button>
			<button class="btn" disabled={!!busy || !converted} onclick={saveConverted}>{t("lab.raw.saveAs")}</button>
		</div>
		{#if converted}
			<div class="cards">
				<div class="stat"><b>{converted.q.sample_rate_hz} Hz</b><span>{t("lab.q.sampleRate")}</span></div>
				<div class="stat"><b>{converted.q.revolutions}</b><span>{t("lab.q.revolutions")}</span></div>
				<div class="stat"><b>{converted.q.speed_mean_rad_s} rad/s</b><span>{t("lab.q.meanSpeed", { speed_cv: (converted.q.speed_cv * 100).toFixed(1) })}</span></div>
				<div class="stat"><b>{converted.q.dropouts}</b><span>{t("lab.q.dropped")}</span></div>
				{#if converted.q.time_offset_s !== null}<div class="stat"><b>{converted.q.time_offset_s} s</b><span>{t("lab.q.videoOffset")}</span></div>{/if}
			</div>
			{#if converted.q.warnings.length}
				<div class="notice"><b>{t("lab.q.readFirst")}</b><ul style="margin:4px 0 0 18px; padding:0">{#each converted.q.warnings as w}<li>{w}</li>{/each}</ul></div>
			{:else}
				<p class="notice info">{t("lab.q.clean")}</p>
			{/if}
			{#if timeSeries}
				<p class="muted">{t("lab.q.torqueChart", { lo: timeSeries.lo.toFixed(4), hi: timeSeries.hi.toFixed(4) })}</p>
				<svg viewBox="0 0 300 100" class="chart"><polyline points={timeSeries.pts} fill="none" stroke="var(--blue)" stroke-width="1.2" /></svg>
			{/if}
		{/if}
	</div>

	<div class="card">
		<h3>{t("lab.import.title")}</h3>
		<div class="row">
			<label class="btn inline" style="cursor:pointer">{t("lab.import.choose")} <input type="file" accept=".csv,.json" onchange={pick} hidden /></label>
			<label>{t("lab.import.name")} <input type="text" bind:value={newName} size="12" /></label>
			<label>{t("lab.import.kind")}
				<select bind:value={kind}><option value="motor_no_wind">{t("lab.import.kind.motor")}</option><option value="fan">{t("lab.import.kind.fan")}</option></select>
			</label>
			<label>{t("lab.import.crankSpeed")} <input type="number" step="0.1" bind:value={omega} /></label>
			{#if kind === "fan"}<label>{t("lab.import.windSpeed")} <input type="number" step="0.5" min="0" bind:value={wind} /></label>{/if}
			<label class="inline"><input type="checkbox" bind:checked={synthetic} /> {t("lab.import.synthetic")}</label>
			<button class="btn primary" disabled={!!busy || !channels} onclick={save}>{t("lab.import.save")}</button>
		</div>
		<small>{t("lab.import.csvHint")}<code>t,psi,torque,x</code>{t("lab.import.csvColumns", { fileName: fileName ? t("lab.import.picked", { fileName: fileName }) : "" })}</small>
	</div>

	<div class="card">
		<h3>{t("lab.compare.title")}</h3>
		<div class="row center">
			<label>{t("lab.compare.measurement")}
				<select bind:value={mId}>
					<option value="">{t("common.choose")}</option>
					{#each measurements as m}<option value={m.id}>{m.name}{m.synthetic ? t("lab.compare.syntheticTag") : ""}</option>{/each}
				</select>
			</label>
			<label>{t("lab.compare.simRun")}
				<select bind:value={runId}>
					<option value="">{t("common.choose")}</option>
					{#each runs as r}<option value={r.id}>{r.design_name || r.design_id} · {r.id.slice(0, 10)}…</option>{/each}
				</select>
			</label>
			<button class="btn primary" disabled={!!busy || !mId || !runId} onclick={compare}>{t("lab.compare.run")}</button>
		</div>
		{#if cmp && chart}
			<div class="cards">
				<div class="stat"><b>{cmp.distance === null ? "–" : cmp.distance.toFixed(3)}</b><span>{t("lab.compare.mismatch")}</span></div>
				{#if cmp.stride_measured !== null && cmp.stride_simulated !== null}
					<div class="stat"><b>{cmp.stride_measured.toFixed(3)} / {cmp.stride_simulated.toFixed(3)}</b><span>{t("lab.compare.stride")}</span></div>
				{/if}
			</div>
			<p class="muted">{t("lab.compare.chartTitle", { lo: chart.lo.toFixed(4), hi: chart.hi.toFixed(4) })}<span style="color:var(--blue)"> {t("lab.compare.legendMeasured")}</span> <span style="color:var(--accent)"> {t("lab.compare.legendSimulated")}</span></p>
			<svg viewBox="0 0 300 100" class="chart"><polyline points={chart.m} fill="none" stroke="var(--blue)" stroke-width="1.5" /><polyline points={chart.s} fill="none" stroke="var(--accent)" stroke-width="1.5" /></svg>
			<small>{t("lab.compare.mismatchDef")}</small>
		{/if}
	</div>

	<div class="card">
		<h3>{t("lab.calib.title")}</h3>
		<div class="row center">
			<label class="inline"><input type="checkbox" bind:checked={calParams.contact_stiffness} /> {t("param.contactStiffness")}</label>
			<label class="inline"><input type="checkbox" bind:checked={calParams.friction} /> {t("param.friction")}</label>
			<button class="btn primary" disabled={!!busy || !mId} onclick={calibrate}>{t("lab.calib.run")}</button>
		</div>
		{#if profile}
			<table class="tbl">
				<thead><tr><th colspan="2">{t("lab.calib.result", { name: profile.name })}</th></tr></thead>
				<tbody>
					{#each Object.entries(profile.parameters) as [k, v]}<tr><td>{k}</td><td>{v.toPrecision(4)}</td></tr>{/each}
					<tr><td>{t("lab.calib.residual")}</td><td>{profile.provenance.residual.toFixed(3)}</td></tr>
					<tr><td>{t("lab.calib.method")}</td><td>{profile.provenance.method}</td></tr>
				</tbody>
			</table>
			{#if profile.provenance.synthetic}<p class="notice">{t("lab.calib.syntheticWarning")}</p>{/if}
		{/if}
		<p class="notice info">{t("lab.calib.caveat")}</p>
	</div>
</div>


<style>
	.chart { width: 100%; max-width: 560px; height: 130px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); }
</style>