<script lang="ts">
import {
	JANSEN_LENGTHS,
	JANSEN_PARAM_NAMES,
	type JansenParams,
} from "strandbeest-core";
import { call, download } from "./api";
import Evolver from "./Evolver.svelte";
import LinkageViewer from "./LinkageViewer.svelte";
import { currentDesign, store } from "./store.svelte";
import WindPanel from "./WindPanel.svelte";

let saved = $state<string[]>([]);
let pick = $state("");
let msg = $state("");

async function guard(fn: () => Promise<void>) {
	msg = "";
	try {
		await fn();
	} catch (e) {
		msg = e instanceof Error ? e.message : String(e);
	}
}

const refresh = () =>
	guard(async () => {
		saved = await call("/designs");
	});
const save = () =>
	guard(async () => {
		await call("/designs", currentDesign());
		msg = `已保存：${store.name}`;
		saved = await call("/designs");
	});

function apply(doc: any) {
	const p = doc?.linkage?.params;
	if (!p || !JANSEN_PARAM_NAMES.every((n) => typeof p[n] === "number")) {
		throw new Error(
			"这个设计的连杆不是 Jansen 拓扑，设计器暂时只能编辑 13 个 Jansen 长度",
		);
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
		if (!v.ok) throw new Error(`设计文件无效：${v.errors.join("; ")}`);
		apply(doc);
	});
}
</script>

<section>
	<h2>设计</h2>
	<p>拖动滑块改变连杆长度，观察脚的轨迹（橙色）。默认是 Theo Jansen 的 13 个数字。</p>
	<LinkageViewer bind:params={store.params} />
	<div class="row">
		<button onclick={() => (store.params = { ...JANSEN_LENGTHS })}>恢复 Jansen 原始参数</button>
		<label>名称 <input type="text" bind:value={store.name} size="20" /></label>
		<label>腿数 <input type="number" min="2" max="12" bind:value={store.legs} /></label>
		<label>1 单位 = <input type="number" min="0.5" max="10" step="0.5" bind:value={store.unitMm} /> mm</label>
	</div>
	<div class="row">
		<button onclick={save}>保存到后端</button>
		<button onclick={refresh}>刷新列表</button>
		<select bind:value={pick}>
			<option value="">选择已保存的设计…</option>
			{#each saved as n}<option value={n}>{n}</option>{/each}
		</select>
		<button disabled={!pick} onclick={load}>加载</button>
		<button onclick={exportJson}>下载设计 JSON</button>
		<label class="file">导入设计 JSON <input type="file" accept="application/json" onchange={importJson} /></label>
	</div>
	{#if msg}<p class="msg">{msg}</p>{/if}

	<h3>风能带得动吗？</h3>
	<WindPanel params={store.params} />
	<h3>让它自己演化</h3>
	<p>遗传算法在浏览器里运行（Web Worker），从当前参数出发搜索。</p>
	<Evolver params={store.params} onapply={(p) => (store.params = p)} />
</section>

<style>
	.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; margin: 8px 0; font-size: 14px; }
	input[type="number"] { width: 70px; }
	.msg { color: #c0392b; font-size: 13px; }
	.file input { font-size: 12px; }
</style>
