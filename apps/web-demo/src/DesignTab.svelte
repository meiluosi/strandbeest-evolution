<script lang="ts">
import {
	JANSEN_LENGTHS,
	JANSEN_PARAM_NAMES,
	type JansenParams,
} from "strandbeest-core";
import { call, download } from "./api";
import Evolver from "./Evolver.svelte";
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
		msg = { text: `已保存：${store.name}`, kind: "info" };
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

<div class="stack">
	<div class="grid2">
		<div class="card">
			<h2>脚的轨迹</h2>
			<p class="muted">拖动右边的长度，看脚（橙点）怎么走。默认是 Theo Jansen 的 13 个数字。</p>
			<LinkageViewer params={store.params} bind:metrics />
			{#if metrics}
				<div class="row">
					<div class="chip"><b>{(metrics.duty * 100).toFixed(0)}%</b><span>着地占比</span></div>
					<div class="chip"><b>{metrics.lift.toFixed(1)}</b><span>抬腿高度</span></div>
					<div class="chip"><b>{metrics.strokeLength.toFixed(1)}</b><span>平底长度</span></div>
					<small>长度单位：1 单位 = {store.unitMm} mm</small>
				</div>
			{:else}
				<p class="notice error">这组长度装不起来：脚轨迹没有定义。</p>
			{/if}
		</div>
		<div class="card">
			<div class="row center" style="justify-content: space-between; margin-top: 0">
				<h2 style="margin: 0">连杆长度</h2>
				<button class="btn small" onclick={() => (store.params = { ...JANSEN_LENGTHS })}>恢复 Jansen 原值</button>
			</div>
			<LengthSliders bind:params={store.params} />
		</div>
	</div>

	<div class="card">
		<h2>设计文件</h2>
		<div class="row">
			<label>名称 <input type="text" bind:value={store.name} size="20" /></label>
			<label>腿数 <input type="number" min="2" max="12" bind:value={store.legs} /></label>
			<label>1 单位 = (mm) <input type="number" min="0.5" max="10" step="0.5" bind:value={store.unitMm} /></label>
		</div>
		<div class="row center">
			<button class="btn primary" onclick={save}>保存到后端</button>
			<select bind:value={pick} onfocus={refresh}>
				<option value="">加载已保存的设计…</option>
				{#each saved as n}<option value={n}>{n}</option>{/each}
			</select>
			<button class="btn" disabled={!pick} onclick={load}>加载</button>
			<button class="btn" onclick={exportJson}>下载 JSON</button>
			<label class="inline btn" style="cursor:pointer">导入 JSON <input type="file" accept="application/json" onchange={importJson} hidden /></label>
		</div>
		{#if msg}<p class="notice {msg.kind}">{msg.text}</p>{/if}
	</div>

	<details class="card">
		<summary><b>风能带得动吗？</b> <small>简化的准静态估算，假设很多，只用来比较设计</small></summary>
		<WindPanel params={store.params} />
	</details>
	<details class="card">
		<summary><b>让它自己演化</b> <small>遗传算法在浏览器里跑（Web Worker）</small></summary>
		<Evolver params={store.params} onapply={(p) => (store.params = p)} />
	</details>
</div>
