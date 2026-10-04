<script lang="ts">
import { defaultDesign, type JansenParams } from "strandbeest-core";

let { params }: { params: JansenParams } = $props();

let api = $state("http://127.0.0.1:8000");
let legs = $state(6);
let unitMm = $state(2);
let clearance = $state(0.3);
let busy = $state("");
let error = $state("");
let evalResult = $state<{
	gait: { duty: number; lift: number; width: number; stroke_length: number };
} | null>(null);
let exportResult = $state<{
	parts: number;
	layers_per_leg: number;
	download: string;
	checks: {
		name: string;
		status: string;
		value: number | string;
		limit: string;
	}[];
} | null>(null);
let runResult = $state<{
	metrics: Record<string, number | null>;
	stalled: boolean;
} | null>(null);
let torque = $state<{ psi: number[]; torque: number[] } | null>(null);

const design = $derived.by(() => {
	const d = defaultDesign(params);
	d.walker.legs = legs;
	d.walker.unit_m = unitMm / 1000;
	d.manufacturing.clearance_mm = clearance;
	return d;
});

async function call(path: string, body?: unknown) {
	const r = await fetch(api + path, {
		method: body === undefined ? "GET" : "POST",
		headers: { "content-type": "application/json" },
		body: body === undefined ? undefined : JSON.stringify(body),
	});
	if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
	return r.json();
}

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
	guard("评估中", async () => (evalResult = await call("/evaluate", design)));
const exportPack = () =>
	guard("导出中", async () => (exportResult = await call("/exports", design)));
const simulate = () =>
	guard("仿真中（约十几秒）", async () => {
		runResult = null;
		torque = null;
		const { job_id } = await call("/runs", {
			design,
			overrides: { run: { revolutions: 1.5 } },
		});
		for (;;) {
			const j = await call(`/jobs/${job_id}`);
			if (j.status === "failed") throw new Error(j.error);
			if (j.status === "done") {
				runResult = j.result;
				torque = await call(`/runs/${j.result.id}/series`);
				return;
			}
			await new Promise((r) => setTimeout(r, 1000));
		}
	});

const spark = $derived.by(() => {
	if (!torque || torque.torque.length < 2) return "";
	const v = torque.torque;
	const lo = Math.min(...v);
	const hi = Math.max(...v);
	return v
		.map(
			(y, i) =>
				`${(i / (v.length - 1)) * 300},${95 - ((y - lo) / (hi - lo || 1)) * 85}`,
		)
		.join(" ");
});
</script>

<div class="fab">
	<div class="row">
		<label>腿数 <input type="number" min="2" max="12" bind:value={legs} /></label>
		<label>1 单位 = <input type="number" min="0.5" max="10" step="0.5" bind:value={unitMm} /> mm</label>
		<label>配合间隙 <input type="number" min="0" max="1" step="0.05" bind:value={clearance} /> mm</label>
		<label>后端 <input type="text" bind:value={api} size="22" /></label>
	</div>
	<div class="row">
		<button disabled={!!busy} onclick={evaluate}>评估步态</button>
		<button disabled={!!busy} onclick={exportPack}>可打印性检查 + 导出打印包</button>
		<button disabled={!!busy} onclick={simulate}>高保真仿真（MuJoCo）</button>
		{#if busy}<span>{busy}…</span>{/if}
	</div>
	{#if error}<p class="err">出错：{error}（后端启动了吗？<code>strandbeest-api</code>）</p>{/if}

	{#if evalResult}
		<p>步态：着地占比 {(evalResult.gait.duty * 100).toFixed(0)}% · 抬腿 {evalResult.gait.lift.toFixed(1)} · 宽 {evalResult.gait.width.toFixed(1)} · 着地段 {evalResult.gait.stroke_length.toFixed(1)}（长度单位）</p>
	{/if}

	{#if exportResult}
		<table>
			<thead><tr><th>检查</th><th>结果</th><th>值</th><th>要求</th></tr></thead>
			<tbody>
				{#each exportResult.checks as c}
					<tr class={c.status}><td>{c.name}</td><td>{c.status}</td><td>{c.value}</td><td>{c.limit}</td></tr>
				{/each}
			</tbody>
		</table>
		<p>{exportResult.parts} 种零件，每条腿 {exportResult.layers_per_leg} 层。 <a href={api + exportResult.download}>下载打印包（STL、物料清单、装配说明）</a></p>
	{/if}

	{#if runResult}
		<p>
			仿真：每转步幅 {runResult.metrics.stride_per_rev?.toFixed(3)} m · 平均速度 {runResult.metrics.mean_speed?.toFixed(3)} m/s ·
			平均扭矩 {runResult.metrics.mean_torque?.toFixed(3)} N·m · 峰值 {runResult.metrics.peak_torque?.toFixed(3)} N·m
			{#if runResult.stalled}（<b>卡住了</b>）{/if}
		</p>
		<svg viewBox="0 0 300 100" class="chart"><polyline points={spark} fill="none" stroke="#e5733f" stroke-width="2" /></svg>
	{/if}
	<small>仿真的接触、摩擦、关节间隙都是假设值，尚未用实测校准；导出的零件是第一版，请先打印单条腿手摇验证。</small>
</div>

<style>
	.fab { display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
	.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; }
	input[type="number"] { width: 70px; }
	table { border-collapse: collapse; }
	td, th { border: 1px solid #8884; padding: 3px 8px; text-align: left; }
	tr.fail td { background: #e5733f33; }
	tr.warn td { background: #e5c13f33; }
	.chart { width: 100%; max-width: 480px; height: 110px; border: 1px solid #8884; border-radius: 8px; }
	.err { color: #c0392b; }
	small { opacity: 0.7; }
</style>
