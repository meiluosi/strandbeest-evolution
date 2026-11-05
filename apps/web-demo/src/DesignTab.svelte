<script lang="ts">
import {
	type LinkageSpec,
	migrateDesign,
	type Operation,
	trace,
} from "strandbeest-core";
import designSchema from "../../../schemas/design.schema.json";
import AssetBrowserPanel from "./AssetBrowserPanel.svelte";
import { call, download } from "./api";
import Evolver from "./Evolver.svelte";
import {
	branchDesign,
	commit,
	currentDesign,
	edit,
	editor,
	newFromLinkage,
	op,
	openDocument,
	previewDesign,
	setLength,
	setProperty,
} from "./editor.svelte";
import HistoryPanel from "./HistoryPanel.svelte";
import { t } from "./i18n/index.svelte";
import LengthSliders from "./LengthSliders.svelte";
import LinkageViewer, { type LengthEdit } from "./LinkageViewer.svelte";
import MapElitesGrid from "./MapElitesGrid.svelte";
import Onboarding from "./Onboarding.svelte";
import { PRESETS } from "./presets";
import SchemaForm from "./SchemaForm.svelte";
import type { SchemaField } from "./schema-form";
import { designCardPng, saveBlob } from "./share-export";
import { encodeShare, STATIC } from "./static";
import { view } from "./store.svelte";
import WindPanel from "./WindPanel.svelte";

let {
	oncommand,
	onsim,
	onevolve,
	evolve = false,
}: {
	oncommand: () => void;
	onsim: () => void;
	onevolve: () => void;
	evolve?: boolean;
} = $props();
let evolveOpen = $state(false);
$effect(() => {
	if (!evolve) return;
	evolveOpen = true;
	queueMicrotask(() =>
		document.getElementById("evolver")?.scrollIntoView({ block: "start" }),
	);
});

let saved = $state<string[]>([]);
let pick = $state("");
let msg = $state<{ text: string; kind: "info" | "error" } | null>(null);
let busy = $state<"save" | "share" | "card" | "load" | "import" | null>(null);
let metrics = $state<{
	strokeLength: number;
	lift: number;
	duty: number;
} | null>(null);
let theta = $state(0);
let windDrive = $state(false);
let windOmega = $state<number | null>(null);
let windSpeed = $state(0);
let stalledAt = $state<number | null>(null);
let viewerRef: ReturnType<typeof LinkageViewer> | null = null;

const shown = $derived(previewDesign());
const shownLinkage = $derived(shown.linkage);

const fail = (text: string) => (msg = { text, kind: "error" });
const rejected = (r: { ok: boolean; message?: string }) => {
	msg = r.ok ? null : { text: r.message ?? "", kind: "error" };
};

async function guard(fn: () => Promise<void>, action?: typeof busy) {
	if (action && busy) return;
	msg = null;
	if (action) busy = action;
	try {
		await fn();
	} catch (e) {
		fail(e instanceof Error ? e.message : String(e));
	} finally {
		if (action) busy = null;
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
		msg = { text: t("design.saved", { name: view.name }), kind: "info" };
	}, "save");

function apply(doc: any) {
	if (!doc?.linkage?.params || !Array.isArray(doc.linkage.joints)) {
		throw new Error(t("design.invalid", { join: "linkage" }));
	}
	openDocument(structuredClone(doc));
}

function loadPreset(e: Event) {
	const sel = e.target as HTMLSelectElement;
	const p = PRESETS.find((x) => x.id === sel.value);
	if (p) newFromLinkage(p.spec, p.id);
	sel.value = "";
}

const load = () =>
	guard(async () => apply(await call(`/designs/${pick}`)), "load");
async function share() {
	await guard(async () => {
		const url = `${location.origin}${location.pathname}#d=${await encodeShare(currentDesign())}`;
		history.replaceState(null, "", url);
		await navigator.clipboard.writeText(url);
		msg = { text: t("design.shareCopied"), kind: "info" };
	}, "share");
}
async function exportCard() {
	await guard(async () => {
		const m = metrics;
		const png = await designCardPng({
			title: view.name,
			subtitle: t("card.subtitle", { legs: view.legs }),
			foot: trace(shownLinkage, 180).foot,
			stats: m
				? [
						{
							value: `${(m.duty * 100).toFixed(0)}%`,
							label: t("metric.dutyFactor"),
						},
						{ value: m.lift.toFixed(1), label: t("metric.liftHeight") },
						{ value: m.strokeLength.toFixed(1), label: t("metric.flatLength") },
					]
				: [],
			footer: t("card.footer"),
		});
		saveBlob(`${view.name}.png`, png);
	}, "card");
}
const exportJson = () =>
	download(`${view.name}.json`, JSON.stringify(currentDesign(), null, 2));
async function importJson(e: Event) {
	const f = (e.target as HTMLInputElement).files?.[0];
	if (!f) return;
	await guard(async () => {
		const raw = JSON.parse(await f.text());
		const doc = raw?.schema_version === 1 ? migrateDesign(raw) : raw;
		if (!STATIC) {
			const v = await call("/designs/validate", doc);
			if (!v.ok)
				throw new Error(t("design.invalid", { join: v.errors.join("; ") }));
		}
		apply(doc);
	}, "import");
}

function lengthOp(key: string, value: number): Operation {
	return key in currentDesign().linkage.params
		? op("set_param", { name: key, value })
		: op("set_length", { key, value });
}

function previewLength(key: string, value: number) {
	editor.preview = [lengthOp(key, value)];
}
function commitLength(key: string, value: number) {
	rejected(setLength(key, value));
}

function dragEdit(edits: LengthEdit[] | null, final: boolean) {
	if (!edits) {
		editor.preview = null;
		return;
	}
	const ops = edits.map((e) => lengthOp(e.key, e.value));
	if (!final) {
		editor.preview = ops;
		return;
	}
	rejected(ops.length ? commit(ops) : { ok: true });
}

function applySchemaField(field: SchemaField, value: unknown) {
	if (field.path === "walker.legs" && typeof value === "number") {
		rejected(edit("array_legs", { legs: Math.round(value) }));
		return;
	}
	rejected(setProperty(field.pointer, value));
}

function applyEvolved(spec: LinkageSpec) {
	const parent = currentDesign();
	const now = parent.linkage.params;
	const ops = Object.entries(spec.params)
		.filter(([k, v]) => now[k] !== v)
		.map(([k, v]) =>
			op("set_param", { name: k, value: v }, "evolver: best of the run", {
				kind: "algorithm",
				id: "ga",
			}),
		);
	if (!ops.length) return;
	branchDesign(`${parent.name}-evolved`);
	rejected(commit(ops));
}
</script>

<div class="design-workspace">
	<header class="workspace-header">
		<div>
			<span class="eyebrow">{t("design.workspaceEyebrow")}</span>
			<h2>{t("design.workspaceTitle")}</h2>
			<p>{t("design.workspaceDescription")}</p>
		</div>
		<div class="workspace-actions">
			<button class="btn" onclick={oncommand}>{t("palette.open")}<kbd>Ctrl K</kbd></button>
			<button class="btn primary" onclick={onsim}>{t("design.toSimulation")}</button>
		</div>
	</header>

	{#if msg}<p class="notice {msg.kind}" role={msg.kind === "error" ? "alert" : "status"}>{msg.text}</p>{/if}

	<div class="design-grid">
		<section class="mechanism-panel" aria-label={t("design.footPath")}>
			<header class="panel-heading">
				<div>
					<span class="eyebrow">{t("design.mechanismEyebrow")}</span>
					<h3>{t("design.footPath")}</h3>
				</div>
				<span class="evidence-label">{t("design.kinematicEvidence")}</span>
			</header>
			<p class="canvas-hint">{t("design.footPath.hint")}</p>
			<LinkageViewer
				bind:this={viewerRef}
				spec={shownLinkage}
				bind:metrics
				bind:theta
				legs={view.legs}
				{windOmega}
				{windSpeed}
				{stalledAt}
				onedit={dragEdit}
			/>
			{#if metrics}
				<div class="metric-strip" aria-label={t("design.metrics")}>
					<div class="metric"><b>{(metrics.duty * 100).toFixed(0)}%</b><span>{t("metric.dutyFactor")}</span></div>
					<div class="metric"><b>{metrics.lift.toFixed(1)}</b><span>{t("metric.liftHeight")}</span></div>
					<div class="metric"><b>{metrics.strokeLength.toFixed(1)}</b><span>{t("metric.flatLength")}</span></div>
					<small>{t("design.unitNote", { unitMm: view.unitMm })}</small>
				</div>
			{:else}
				<p class="notice error geometry-error" role="alert">{t("design.unassemblable")}</p>
			{/if}
		</section>

		<aside class="inspector" aria-label={t("design.lengths")}>
			<header class="inspector-heading">
				<div><span class="eyebrow">{t("design.inspectorEyebrow")}</span><h3>{t("design.lengths")}</h3></div>
				<select class="small" onchange={loadPreset} aria-label={t("design.preset")}>
					<option value="">{t("design.preset")}</option>
					{#each PRESETS as p}<option value={p.id}>{p.id}</option>{/each}
				</select>
			</header>
			<p class="inspector-note">{t("design.editHint")} {t("design.unitNote", { unitMm: view.unitMm })}</p>
			<LengthSliders spec={shownLinkage} onpreview={previewLength} oncommit={commitLength} />
		</aside>
	</div>

	<Onboarding onevolve={onevolve} {onsim} />

	<div class="secondary-panels">
		<details class="card">
			<summary><b>{t("design.configuration")}</b><small>{t("design.configurationHint")}</small></summary>
			<SchemaForm
				schema={designSchema as Record<string, unknown>}
				sections={["", "walker"]}
				value={shown as unknown as Record<string, unknown>}
				onchange={applySchemaField}
			/>
		</details>

		<details class="card">
			<summary><b>{t("design.file")}</b><small>{t("design.fileHint")}</small></summary>
			<div class="file-actions">
				{#if !STATIC}
					<button class="btn primary" disabled={busy !== null} onclick={save}>{busy === "save" ? t("design.saving") : t("design.saveBackend")}</button>
					<select bind:value={pick} onfocus={refresh} aria-label={t("design.loadPlaceholder")}>
						<option value="">{t("design.loadPlaceholder")}</option>
						{#each saved as n}<option value={n}>{n}</option>{/each}
					</select>
					<button class="btn" disabled={!pick || busy !== null} onclick={load}>{busy === "load" ? t("design.loading") : t("common.load")}</button>
				{/if}
				<button class="btn" class:primary={STATIC} disabled={busy !== null} onclick={share}>{busy === "share" ? t("design.sharing") : t("design.share")}</button>
				<button class="btn" disabled={busy !== null} onclick={exportCard}>{busy === "card" ? t("design.exporting") : t("design.exportCard")}</button>
				<button class="btn" onclick={exportJson}>{t("design.downloadJson")}</button>
				<label class="inline btn import-button" aria-disabled={busy !== null}>{busy === "import" ? t("design.importing") : t("design.importJson")}<input type="file" accept="application/json" disabled={busy !== null} onchange={importJson} hidden /></label>
			</div>
		</details>

		<details class="card">
			<summary><b>{t("assets.title")}</b><small>{t("assets.subtitle")}</small></summary>
			<AssetBrowserPanel onmessage={(text, kind = "info") => (msg = { text, kind })} />
		</details>
		<details class="card">
			<summary><b>{t("history.title")}</b><small>{t("history.subtitle")}</small></summary>
			<HistoryPanel onmessage={fail} />
		</details>
		<details class="card">
			<summary><b>{t("wind.title")}</b><small>{t("wind.subtitle")}</small></summary>
			<WindPanel
				spec={shownLinkage}
				bind:theta
				bind:windDrive
				bind:windOmega
				bind:windSpeed
				bind:stalledAt
				ongust={() => viewerRef?.triggerGust()}
			/>
		</details>
		<details class="card" id="evolver" bind:open={evolveOpen}>
			<summary><b>{t("evolve.title")}</b><small>{t("evolve.subtitle")}</small></summary>
			<Evolver spec={view.linkage} onapply={applyEvolved} />
		</details>
		<details class="card" id="map-elites">
			<summary><b>{t("map_elites.title")}</b><small>{t("map_elites.subtitle")}</small></summary>
			<MapElitesGrid onload={apply} />
		</details>
	</div>
</div>

<style>
	.design-workspace { max-width: 1480px; margin: 0 auto; }
	.workspace-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
	.eyebrow { display: block; color: var(--accent-strong); font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: 0.13em; text-transform: uppercase; }
	.workspace-header h2 { margin-top: 4px; font-size: clamp(24px, 2.3vw, 32px); letter-spacing: -0.04em; }
	.workspace-header p { margin-top: 5px; color: var(--text-soft); }
	.workspace-actions { display: flex; gap: 8px; flex: 0 0 auto; }
	.workspace-actions .btn { display: inline-flex; align-items: center; gap: 10px; }
	kbd { font-family: var(--font-mono); font-size: 10px; opacity: 0.65; }
	.design-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
	.mechanism-panel, .inspector { min-width: 0; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-md); box-shadow: var(--shadow-sm); }
	.mechanism-panel { overflow: hidden; }
	.panel-heading, .inspector-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 16px; border-bottom: 1px solid var(--line); }
	.panel-heading h3, .inspector-heading h3 { margin: 2px 0 0; }
	.evidence-label { color: var(--success); background: var(--success-soft); border-radius: 999px; padding: 3px 9px; font-size: 11px; white-space: nowrap; }
	.canvas-hint { margin: 0; padding: 10px 16px 0; color: var(--text-muted); font-size: 12px; }
	.inspector { padding-bottom: 12px; }
	.inspector-heading { align-items: flex-start; }
	.inspector-heading select { max-width: 132px; font-size: 11px; }
	.inspector-note { margin: 0; padding: 12px 16px 4px; color: var(--text-muted); font-size: 11px; }
	.metric-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; border-top: 1px solid var(--line); background: var(--line); }
	.metric { display: flex; flex-direction: column; gap: 2px; padding: 13px 16px; background: var(--surface-raised); }
	.metric b { font-family: var(--font-mono); font-size: 21px; font-weight: 500; }
	.metric span { color: var(--text-muted); font-size: 11px; }
	.metric-strip > small { grid-column: 1 / -1; padding: 7px 16px; background: var(--surface-raised); }
	.geometry-error { margin: 12px 16px 16px; }
	.secondary-panels { margin-top: 16px; }
	.secondary-panels details { scroll-margin-top: 90px; }
	.secondary-panels summary small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.file-actions { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 10px; }
	.file-actions select { max-width: 240px; }
	.import-button { cursor: pointer; }
	.import-button[aria-disabled="true"] { opacity: 0.45; cursor: not-allowed; }
	@media (max-width: 1120px) {
		.design-grid { grid-template-columns: minmax(0, 1fr) 280px; gap: 12px; }
		.panel-heading, .inspector-heading { padding: 11px 12px; }
		.inspector-heading { flex-direction: column; }
		.inspector-heading select { max-width: 100%; width: 100%; }
	}
	@media (max-width: 920px) {
		.design-grid { grid-template-columns: minmax(0, 1fr); }
		.inspector-heading { flex-direction: row; align-items: center; }
		.inspector-heading select { width: auto; max-width: 160px; }
	}
	@media (max-width: 600px) {
		.workspace-header { align-items: flex-start; flex-direction: column; gap: 14px; margin-bottom: 16px; }
		.workspace-actions { width: 100%; }
		.workspace-actions .btn { flex: 1; justify-content: center; }
		.workspace-actions kbd { display: none; }
		.panel-heading { align-items: flex-start; }
		.evidence-label { white-space: normal; text-align: right; }
		.canvas-hint { padding: 9px 12px 0; }
		.metric { padding: 11px 10px; }
		.metric b { font-size: 18px; }
		.secondary-panels summary { align-items: flex-start; flex-wrap: wrap; }
		.secondary-panels summary small { width: 100%; white-space: normal; }
		.file-actions .btn, .file-actions select { max-width: 100%; }
	}
</style>
