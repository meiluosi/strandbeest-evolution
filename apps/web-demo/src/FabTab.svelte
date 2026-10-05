<script lang="ts">
import { call } from "./api";
import { t } from "./i18n/index.svelte";
import { currentDesign, store } from "./store.svelte";
import Viewer3D from "./Viewer3D.svelte";

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

<div class="stack">
	<div class="card">
		<h2>{t("nav.fab")}</h2>
		<p class="muted">{t("design.current")}<b>{store.name}</b>{t("fab.designSummary", { legs: store.legs, unitMm: store.unitMm })}</p>
		<div class="row center">
			<label>{t("fab.clearance")} <input type="number" min="0" max="1" step="0.05" bind:value={store.clearance} /></label>
			<button class="btn" disabled={!!busy} onclick={evaluate}>{t("fab.evalGait")}</button>
			<button class="btn primary" disabled={!!busy} onclick={exportPack}>{t("fab.checkExport")}</button>
			{#if busy}<span class="muted"><span class="spin"></span>{busy}…</span>{/if}
		</div>
		{#if error}<p class="notice error">{t("fab.error.before", { error: error })}<code>strandbeest-api</code>{t("common.closeParen")}</p>{/if}
		{#if gait}
			<div class="row">
				<div class="chip"><b>{(gait.duty * 100).toFixed(0)}%</b><span>{t("metric.dutyFactor")}</span></div>
				<div class="chip"><b>{gait.lift.toFixed(1)}</b><span>{t("fab.lift")}</span></div>
				<div class="chip"><b>{gait.stroke_length.toFixed(1)}</b><span>{t("metric.flatLength")}</span></div>
			</div>
		{/if}
	</div>

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
					params={store.params}
					unitMm={designAtExport?.walker.unit_m ? designAtExport.walker.unit_m * 1000 : store.unitMm}
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
	figure { margin: 0; text-align: center; font-size: 12px; border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
	svg { width: 100%; height: 70px; }
</style>