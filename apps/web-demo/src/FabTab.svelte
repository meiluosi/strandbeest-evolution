<script lang="ts">
import { call } from "./api";
import DesignContextBar from "./DesignContextBar.svelte";
import { currentDesign, editor, setProperty } from "./editor.svelte";
import { t } from "./i18n/index.svelte";
import StateBadge from "./StateBadge.svelte";
import { store, view } from "./store.svelte";
import Viewer3D from "./Viewer3D.svelte";
import WorkspaceHeader from "./WorkspaceHeader.svelte";

type Check = {
	name: string;
	status: string;
	value: number | string;
	limit: string;
	note?: string;
};
type Outline = { exterior: number[][]; interiors: number[][][] };
type Part = {
	kind: string;
	qty: number;
	bounds_mm: number[];
	note: string;
	outline?: Outline;
};

let busy = $state("");
let error = $state("");
let gait = $state<{
	duty: number;
	lift: number;
	width: number;
	stroke_length: number;
} | null>(null);
let pack = $state<{
	parts: number;
	layers_per_leg: number;
	download: string;
	checks: Check[];
	export_id: string;
} | null>(null);
let manifest = $state<any>(null);
let designAtExport = $state<ReturnType<typeof currentDesign> | null>(null);

async function guard(label: string, fn: () => Promise<void>) {
	busy = label;
	error = "";
	try {
		await fn();
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	} finally {
		busy = "";
	}
}

const evaluate = () =>
	guard(t("fab.busy.evaluating"), async () => {
		gait = (await call("/evaluate", currentDesign())).gait;
	});
const exportPack = () =>
	guard(t("fab.busy.exporting"), async () => {
		designAtExport = currentDesign();
		const r = await call("/exports", designAtExport);
		pack = r;
		manifest = await call(`/exports/${r.export_id}/parts`);
	});

function path(o: Outline): string {
	const ring = (r: number[][]) =>
		`M${r.map((p) => `${p[0]},${-(p[1] as number)}`).join("L")}Z`;
	return [ring(o.exterior), ...o.interiors.map(ring)].join(" ");
}
function box(o: Outline): string {
	const xs = o.exterior.map((p) => p[0] as number);
	const ys = o.exterior.map((p) => -(p[1] as number));
	const [x0, x1, y0, y1] = [
		Math.min(...xs),
		Math.max(...xs),
		Math.min(...ys),
		Math.max(...ys),
	];
	return `${x0 - 2} ${y0 - 2} ${x1 - x0 + 4} ${y1 - y0 + 4}`;
}
const parts = $derived(
	Object.entries((manifest?.parts ?? {}) as Record<string, Part>),
);
const counts = $derived({
	fail: pack?.checks.filter((c) => c.status === "fail").length ?? 0,
	warn: pack?.checks.filter((c) => c.status === "warn").length ?? 0,
});
</script>

<div class="fab-workspace">
	<WorkspaceHeader
		eyebrow={t("fab.workspaceEyebrow")}
		title={t("fab.workspaceTitle")}
		description={t("fab.workspaceDescription")}
	>
		{#snippet actions()}
			<StateBadge label={busy ? `${busy}…` : t("scenes.source.backend")} tone={busy ? "accent" : "info"} live={!!busy} />
			<button class="btn primary" disabled={!!busy} onclick={exportPack}>{t("fab.checkExport")}</button>
		{/snippet}
	</WorkspaceHeader>
	<DesignContextBar name={view.name} designId={view.designId} legs={view.legs} editSteps={editor.steps.length} />
	<section class="card fabrication-config" aria-labelledby="fabrication-config-title">
		<span class="section-eyebrow">{t("fab.configEyebrow")}</span>
		<h2 id="fabrication-config-title">{t("fab.configTitle")}</h2>
		<p class="muted">{t("fab.configHint")}</p>
		<div class="row center">
			<label>{t("fab.clearance")} <input type="number" min="0" max="1" step="0.05" value={view.clearance} onchange={(e) => { const r = setProperty("/manufacturing/clearance_mm", Number.parseFloat((e.target as HTMLInputElement).value)); if (!r.ok) error = r.message ?? ""; }} /></label>
			<button class="btn" disabled={!!busy} onclick={evaluate}>{t("fab.evalGait")}</button>
		</div>
		{#if error}<p class="notice error">{t("fab.error.before", { error: error })}<code>strandbeest-api</code>{t("common.closeParen")}</p>{/if}
		{#if gait}
			<div class="row gait-results">
				<div class="chip"><b>{(gait.duty * 100).toFixed(0)}%</b><span>{t("metric.dutyFactor")}</span></div>
				<div class="chip"><b>{gait.lift.toFixed(1)}</b><span>{t("fab.lift")}</span></div>
				<div class="chip"><b>{gait.stroke_length.toFixed(1)}</b><span>{t("metric.flatLength")}</span></div>
			</div>
		{/if}
	</section>

	{#if pack && manifest}
		<div class="card">
			<h2>{t("fab.checks.title")}
				{#if counts.fail}<span class="badge fail">{t("fab.checks.fail", { fail: counts.fail })}</span>{:else if counts.warn}<span class="badge warn">{t("fab.checks.warn", { warn: counts.warn })}</span>{:else}<span class="badge pass">{t("fab.checks.allPass")}</span>{/if}
			</h2>
			<table class="tbl">
				<thead><tr><th>{t("fab.checks.col.check")}</th><th>{t("fab.checks.col.result")}</th><th>{t("fab.checks.col.value")}</th><th>{t("fab.checks.col.requirement")}</th></tr></thead>
				<tbody>
					{#each pack.checks as c}
						<tr class={c.status === "pass" ? "" : c.status}>
							<td title={c.note}>{c.name}</td><td><span class="badge {c.status}">{c.status}</span></td><td>{c.value}</td><td class="muted">{c.limit}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<div class="row center">
				<a class="btn primary" href={store.api + pack.download} style="text-decoration:none">{t("fab.download")}</a>
				<small>{t("fab.packSummary", { parts: pack.parts, layers_per_leg: pack.layers_per_leg })}</small>
			</div>
			<p class="notice">{t("fab.caveat")}</p>
		</div>

		<div class="card">
			<h2>{t("fab.preview3d")}</h2>
			{#key pack.export_id}
				<Viewer3D
					api={store.api}
					exportId={pack.export_id}
					{manifest}
					spec={view.linkage}
					unitMm={designAtExport?.walker.unit_m ? designAtExport.walker.unit_m * 1000 : view.unitMm}
					thickness={designAtExport?.manufacturing.bar_thickness_mm ?? 3}
				/>
			{/key}
		</div>

		<div class="card">
			<h2>{t("fab.parts")}</h2>
			<div class="cards">
				{#each parts.filter(([, p]) => p.outline) as [name, p]}
					<figure>
						<svg viewBox={box(p.outline as Outline)}><path d={path(p.outline as Outline)} fill-rule="evenodd" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="0.5" /></svg>
						<figcaption>{name} <b>×{p.qty}</b></figcaption>
					</figure>
				{/each}
			</div>
		</div>
	{/if}
</div>


<style>
	.fab-workspace { display: grid; gap: 16px; max-width: 1480px; margin: 0 auto; }
	.fab-workspace > :global(.workspace-header), .fab-workspace > :global(.design-context-bar) { margin-bottom: 0; }
	.fabrication-config { min-width: 0; }
	.section-eyebrow { color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; letter-spacing: 0.12em; }
	.fabrication-config h2 { margin: 4px 0 0; font-size: 18px; }
	.fabrication-config > p { margin: 5px 0 16px; }
	.gait-results { margin-top: 16px; }
	figure { margin: 0; text-align: center; font-size: 12px; border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
	svg { width: 100%; height: 70px; }
</style>