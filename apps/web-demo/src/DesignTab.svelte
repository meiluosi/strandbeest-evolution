<script lang="ts">
import {
	type LinkageSpec,
	migrateDesign,
	type Operation,
	trace,
} from "strandbeest-core";
import designSchema from "../../../schemas/design.schema.json";
import { call, download } from "./api";
import Evolver from "./Evolver.svelte";
import {
	commit,
	currentDesign,
	edit,
	editor,
	newFromLinkage,
	op,
	openDocument,
	previewDesign,
	redo,
	setLength,
	setProperty,
	undo,
} from "./editor.svelte";
import HistoryPanel from "./HistoryPanel.svelte";
import { t } from "./i18n/index.svelte";
import LengthSliders from "./LengthSliders.svelte";
import LinkageViewer, { type LengthEdit } from "./LinkageViewer.svelte";
import Onboarding from "./Onboarding.svelte";
import { PRESETS } from "./presets";
import SchemaForm from "./SchemaForm.svelte";
import type { SchemaField } from "./schema-form";
import { designCardPng, saveBlob } from "./share-export";
import { encodeShare, STATIC } from "./static";
import { view } from "./store.svelte";
import WindPanel from "./WindPanel.svelte";

let { oncommand, onsim }: { oncommand: () => void; onsim: () => void } =
	$props();
let evolveOpen = $state(false);
function goEvolve() {
	evolveOpen = true;
	queueMicrotask(() =>
		document.getElementById("evolver")?.scrollIntoView({ behavior: "smooth" }),
	);
}

let saved = $state<string[]>([]);
let pick = $state("");
let msg = $state<{ text: string; kind: "info" | "error" } | null>(null);
let metrics = $state<{
	strokeLength: number;
	lift: number;
	duty: number;
} | null>(null);

/** what is shown: the committed design, or the draft of a slider / dragged point over it */
const shown = $derived(previewDesign());
const shownLinkage = $derived(shown.linkage);

const fail = (text: string) => (msg = { text, kind: "error" });
const rejected = (r: { ok: boolean; message?: string }) => {
	msg = r.ok ? null : { text: r.message ?? "", kind: "error" };
};

async function guard(fn: () => Promise<void>) {
	msg = null;
	try {
		await fn();
	} catch (e) {
		fail(e instanceof Error ? e.message : String(e));
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
	});

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

const load = () => guard(async () => apply(await call(`/designs/${pick}`)));
async function share() {
	await guard(async () => {
		const url = `${location.origin}${location.pathname}#d=${await encodeShare(currentDesign())}`;
		history.replaceState(null, "", url);
		await navigator.clipboard.writeText(url);
		msg = { text: t("design.shareCopied"), kind: "info" };
	});
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
	});
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
	});
}

// ---- every edit below is an operation in the log -------------------------------------------------------------------
/** Operation that sets a length: a named param uses set_param, an inline number uses set_length. */
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

/** The best genome of the evolver becomes operations by the algorithm, in one undo step. */
function applyEvolved(spec: LinkageSpec) {
	const now = currentDesign().linkage.params;
	const ops = Object.entries(spec.params)
		.filter(([k, v]) => now[k] !== v)
		.map(([k, v]) =>
			op("set_param", { name: k, value: v }, "evolver: best of the run", {
				kind: "algorithm",
				id: "ga",
			}),
		);
	rejected(ops.length ? commit(ops) : { ok: true });
}
</script>

<div class="stack">
	<Onboarding onevolve={goEvolve} {onsim} />
	<div class="row center toolbar">
		<button class="btn small" disabled={!editor.canUndo} onclick={() => rejected(undo())}>{t("history.undo")}</button>
		<button class="btn small" disabled={!editor.canRedo} onclick={() => rejected(redo())}>{t("history.redo")}</button>
		<button class="btn small primary" onclick={oncommand}>{t("palette.open")} <kbd>⌘K</kbd></button>
		<small class="muted">{t("design.editHint")}</small>
	</div>
	{#if msg}<p class="notice {msg.kind}">{msg.text}</p>{/if}
	<div class="grid2">
		<div class="card">
			<h2>{t("design.footPath")}</h2>
			<p class="muted">{t("design.footPath.hint")}</p>
			<LinkageViewer spec={shownLinkage} bind:metrics onedit={dragEdit} />
			{#if metrics}
				<div class="row">
					<div class="chip"><b>{(metrics.duty * 100).toFixed(0)}%</b><span>{t("metric.dutyFactor")}</span></div>
					<div class="chip"><b>{metrics.lift.toFixed(1)}</b><span>{t("metric.liftHeight")}</span></div>
					<div class="chip"><b>{metrics.strokeLength.toFixed(1)}</b><span>{t("metric.flatLength")}</span></div>
					<small>{t("design.unitNote", { unitMm: view.unitMm })}</small>
				</div>
			{:else}
				<p class="notice error">{t("design.unassemblable")}</p>
			{/if}
		</div>
		<div class="card">
			<div class="row center" style="justify-content: space-between; margin-top: 0">
				<h2 style="margin: 0">{t("design.lengths")}</h2>
				<select class="small" onchange={loadPreset} aria-label={t("design.preset")}>
					<option value="">{t("design.preset")}</option>
					{#each PRESETS as p}<option value={p.id}>{p.id}</option>{/each}
				</select>
			</div>
			<LengthSliders spec={shownLinkage} onpreview={previewLength} oncommit={commitLength} />
		</div>
	</div>

	<div class="card">
		<h2>{t("design.file")}</h2>
		<SchemaForm
			schema={designSchema as Record<string, unknown>}
			sections={["", "walker"]}
			value={shown as unknown as Record<string, unknown>}
			onchange={applySchemaField}
		/>
		<div class="row center">
			{#if !STATIC}
				<button class="btn primary" onclick={save}>{t("design.saveBackend")}</button>
				<select bind:value={pick} onfocus={refresh}>
					<option value="">{t("design.loadPlaceholder")}</option>
					{#each saved as n}<option value={n}>{n}</option>{/each}
				</select>
				<button class="btn" disabled={!pick} onclick={load}>{t("common.load")}</button>
			{/if}
			<button class="btn" class:primary={STATIC} onclick={share}>{t("design.share")}</button>
			<button class="btn" onclick={exportCard}>{t("design.exportCard")}</button>
			<button class="btn" onclick={exportJson}>{t("design.downloadJson")}</button>
			<label class="inline btn" style="cursor:pointer">{t("design.importJson")} <input type="file" accept="application/json" onchange={importJson} hidden /></label>
		</div>
		{#if msg}<p class="notice {msg.kind}">{msg.text}</p>{/if}
	</div>

	<details class="card" open>
		<summary><b>{t("history.title")}</b> <small>{t("history.subtitle")}</small></summary>
		<HistoryPanel onmessage={fail} />
	</details>
	<details class="card">
		<summary><b>{t("wind.title")}</b> <small>{t("wind.subtitle")}</small></summary>
		<WindPanel spec={view.linkage} />
	</details>
	<details class="card" id="evolver" bind:open={evolveOpen}>
		<summary><b>{t("evolve.title")}</b> <small>{t("evolve.subtitle")}</small></summary>
		<Evolver spec={view.linkage} onapply={applyEvolved} />
	</details>
</div>
