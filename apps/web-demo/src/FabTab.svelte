<script lang="ts">
import { call } from "./api";
import { currentDesign, store } from "./store.svelte";

type Check = {
	name: string;
	status: string;
	value: number | string;
	limit: string;
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
let parts = $state<Record<string, Part>>({});

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
	guard(
		"评估中",
		async () => (gait = (await call("/evaluate", currentDesign())).gait),
	);
const exportPack = () =>
	guard("导出中", async () => {
		const r = await call("/exports", currentDesign());
		pack = r;
		parts = (await call(`/exports/${r.export_id}/parts`)).parts;
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
	const pad = 2;
	return `${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`;
}
const outlined = $derived(Object.entries(parts).filter(([, p]) => p.outline));
</script>

<section>
	<h2>制造</h2>
	<p>当前设计：{store.name}，{store.legs} 条腿，1 单位 = {store.unitMm} mm（在“设计”页修改）。</p>
	<div class="row">
		<label>配合间隙 <input type="number" min="0" max="1" step="0.05" bind:value={store.clearance} /> mm</label>
		<button disabled={!!busy} onclick={evaluate}>评估步态</button>
		<button disabled={!!busy} onclick={exportPack}>可打印性检查 + 导出打印包</button>
		{#if busy}<span>{busy}…</span>{/if}
	</div>
	{#if error}<p class="err">出错：{error}（后端启动了吗？<code>strandbeest-api</code>）</p>{/if}
	{#if gait}
		<p>步态：着地占比 {(gait.duty * 100).toFixed(0)}% · 抬腿 {gait.lift.toFixed(1)} · 宽 {gait.width.toFixed(1)} · 着地段 {gait.stroke_length.toFixed(1)}（长度单位）</p>
	{/if}
	{#if pack}
		<table>
			<thead><tr><th>检查</th><th>结果</th><th>值</th><th>要求</th></tr></thead>
			<tbody>
				{#each pack.checks as c}
					<tr class={c.status}><td>{c.name}</td><td>{c.status}</td><td>{c.value}</td><td>{c.limit}</td></tr>
				{/each}
			</tbody>
		</table>
		<p>{pack.parts} 种零件，每条腿 {pack.layers_per_leg} 层。 <a href={store.api + pack.download}>下载打印包（STL、物料清单、装配说明）</a></p>
		<h3>零件轮廓（俯视，单位 mm）</h3>
		<div class="grid">
			{#each outlined as [name, p]}
				<figure>
					<svg viewBox={box(p.outline as Outline)}><path d={path(p.outline as Outline)} fill-rule="evenodd" fill="#e5733f55" stroke="currentColor" stroke-width="0.4" /></svg>
					<figcaption>{name} ×{p.qty}</figcaption>
				</figure>
			{/each}
		</div>
	{/if}
	<small>零件和装配方案是第一版，含若干假设（电机孔距、联轴器、压配偏置）；请先打印单条腿和一个销孔做配合测试。</small>
</section>

<style>
	.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; margin: 8px 0; font-size: 14px; }
	input[type="number"] { width: 70px; }
	table { border-collapse: collapse; font-size: 13px; }
	td, th { border: 1px solid #8884; padding: 3px 8px; text-align: left; }
	tr.fail td { background: #e5733f33; }
	tr.warn td { background: #e5c13f33; }
	.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
	figure { margin: 0; text-align: center; font-size: 12px; }
	svg { width: 100%; max-height: 90px; color: inherit; }
	.err { color: #c0392b; }
	small { opacity: 0.7; }
</style>
