<script lang="ts">
import {
	JANSEN_LENGTHS,
	JANSEN_PARAM_NAMES,
	type JansenParams,
} from "strandbeest-core";
import { call, download } from "./api";
import Evolver from "./Evolver.svelte";
import { t } from "./i18n/index.svelte";
import LengthSliders from "./LengthSliders.svelte";
import LinkageViewer from "./LinkageViewer.svelte";
import { currentDesign, store } from "./store.svelte";
import WindPanel from "./WindPanel.svelte";

let saved = $state<string[]>([]);
let pick = $state("");
let msg = $state<{ text: string; kind: "info" | "error" } | null>(null);
let metrics = $state<{
	strokeLength: number;
	lift: number;
	duty: number;
} | null>(null);

async function guard(fn: () => Promise<void>) {
	msg = null;
	try {
		await fn();
	} catch (e) {
		msg = { text: e instanceof Error ? e.message : String(e), kind: "error" };
	}
}

const refresh = () =>
	guard(async () => {
		saved = await call("/designs");
	});
const save = () =>
	guard(async () => {
		await call("/designs", currentDesign());
		saved = await call("/designs");
		msg = { text: t("design.saved", { name: store.name }), kind: "info" };
	});

function apply(doc: any) {
	const p = doc?.linkage?.params;
	if (!p || !JANSEN_PARAM_NAMES.every((n) => typeof p[n] === "number")) {
		throw new Error(t("design.notJansen"));
	}
	store.params = Object.fromEntries(
		JANSEN_PARAM_NAMES.map((n) => [n, p[n]]),
	) as JansenParams;
	store.name = doc.name;
	store.legs = doc.walker.legs;
	store.unitMm = doc.walker.unit_m * 1000;
	store.clearance = doc.manufacturing.clearance_mm;
}

const load = () => guard(async () => apply(await call(`/designs/${pick}`)));
const exportJson = () =>
	download(`${store.name}.json`, JSON.stringify(currentDesign(), null, 2));
async function importJson(e: Event) {
	const f = (e.target as HTMLInputElement).files?.[0];
	if (!f) return;
	await guard(async () => {
		const doc = JSON.parse(await f.text());
		const v = await call("/designs/validate", doc);
		if (!v.ok)
			throw new Error(t("design.invalid", { join: v.errors.join("; ") }));
		apply(doc);
	});
}
</script>

<div class="stack">
	<div class="grid2">
		<div class="card">
			<h2>{t("design.footPath")}</h2>
			<p class="muted">{t("design.footPath.hint")}</p>
			<LinkageViewer params={store.params} bind:metrics />
			{#if metrics}
				<div class="row">
					<div class="chip"><b>{(metrics.duty * 100).toFixed(0)}%</b><span>{t("metric.dutyFactor")}</span></div>
					<div class="chip"><b>{metrics.lift.toFixed(1)}</b><span>{t("metric.liftHeight")}</span></div>
					<div class="chip"><b>{metrics.strokeLength.toFixed(1)}</b><span>{t("metric.flatLength")}</span></div>
					<small>{t("design.unitNote", { unitMm: store.unitMm })}</small>
				</div>
			{:else}
				<p class="notice error">{t("design.unassemblable")}</p>
			{/if}
		</div>
		<div class="card">
			<div class="row center" style="justify-content: space-between; margin-top: 0">
				<h2 style="margin: 0">{t("design.lengths")}</h2>
				<button class="btn small" onclick={() => (store.params = { ...JANSEN_LENGTHS })}>{t("design.resetJansen")}</button>
			</div>
			<LengthSliders bind:params={store.params} />
		</div>
	</div>

	<div class="card">
		<h2>{t("design.file")}</h2>
		<div class="row">
			<label>{t("design.name")} <input type="text" bind:value={store.name} size="20" /></label>
			<label>{t("design.legs")} <input type="number" min="2" max="12" bind:value={store.legs} /></label>
			<label>{t("design.unitMm")} <input type="number" min="0.5" max="10" step="0.5" bind:value={store.unitMm} /></label>
		</div>
		<div class="row center">
			<button class="btn primary" onclick={save}>{t("design.saveBackend")}</button>
			<select bind:value={pick} onfocus={refresh}>
				<option value="">{t("design.loadPlaceholder")}</option>
				{#each saved as n}<option value={n}>{n}</option>{/each}
			</select>
			<button class="btn" disabled={!pick} onclick={load}>{t("common.load")}</button>
			<button class="btn" onclick={exportJson}>{t("design.downloadJson")}</button>
			<label class="inline btn" style="cursor:pointer">{t("design.importJson")} <input type="file" accept="application/json" onchange={importJson} hidden /></label>
		</div>
		{#if msg}<p class="notice {msg.kind}">{msg.text}</p>{/if}
	</div>

	<details class="card">
		<summary><b>{t("wind.title")}</b> <small>{t("wind.subtitle")}</small></summary>
		<WindPanel params={store.params} />
	</details>
	<details class="card">
		<summary><b>{t("evolve.title")}</b> <small>{t("evolve.subtitle")}</small></summary>
		<Evolver params={store.params} onapply={(p) => (store.params = p)} />
	</details>
</div>
