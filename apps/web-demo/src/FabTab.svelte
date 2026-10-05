<script lang="ts">
import { call } from "./api";
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
	guard("评估中", async () => {
		gait = (await call("/evaluate", currentDesign())).gait;
	});
const exportPack = () =>
	guard("导出中", async () => {
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
		<h2>制造</h2>
		<p class="muted">当前设计：<b>{store.name}</b>，{store.legs} 条腿，1 单位 = {store.unitMm} mm（在“设计”页修改）。</p>
		<div class="row center">
			<label>配合间隙 (mm) <input type="number" min="0" max="1" step="0.05" bind:value={store.clearance} /></label>
			<button class="btn" disabled={!!busy} onclick={evaluate}>评估步态</button>
			<button class="btn primary" disabled={!!busy} onclick={exportPack}>检查并导出打印包</button>
			{#if busy}<span class="muted"><span class="spin"></span>{busy}…</span>{/if}
		</div>
		{#if error}<p class="notice error">出错：{error}（后端启动了吗？<code>strandbeest-api</code>）</p>{/if}
		{#if gait}
			<div class="row">
				<div class="chip"><b>{(gait.duty * 100).toFixed(0)}%</b><span>着地占比</span></div>
				<div class="chip"><b>{gait.lift.toFixed(1)}</b><span>抬腿</span></div>
				<div class="chip"><b>{gait.stroke_length.toFixed(1)}</b><span>平底长度</span></div>
			</div>
		{/if}
	</div>

	{#if pack && manifest}
		<div class="card">
			<h2>可打印性检查
				{#if counts.fail}<span class="badge fail">{counts.fail} 项不通过</span>{:else if counts.warn}<span class="badge warn">{counts.warn} 项需注意</span>{:else}<span class="badge pass">全部通过</span>{/if}
			</h2>
			<table class="tbl">
				<thead><tr><th>检查</th><th>结果</th><th>值</th><th>要求</th></tr></thead>
				<tbody>
					{#each pack.checks as c}
						<tr class={c.status === "pass" ? "" : c.status}>
							<td title={c.note}>{c.name}</td><td><span class="badge {c.status}">{c.status}</span></td><td>{c.value}</td><td class="muted">{c.limit}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<div class="row center">
				<a class="btn primary" href={store.api + pack.download} style="text-decoration:none">下载打印包（STL + 物料清单 + 装配说明）</a>
				<small>{pack.parts} 种零件，每条腿 {pack.layers_per_leg} 层</small>
			</div>
			<p class="notice">零件和装配方案是第一版，含若干假设（电机孔距、联轴器、压配偏置），请先打印一根杆加一个销做配合测试。</p>
		</div>

		<div class="card">
			<h2>三维预览</h2>
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
			<h2>零件</h2>
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
