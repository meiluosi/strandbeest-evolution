<script lang="ts">
import {
	type GAState,
	genomeToParams,
	type JansenParams,
	paramsToGenome,
} from "strandbeest-core";
import type { WorkerRequest } from "./ga.worker";

let {
	params,
	onapply,
}: { params: JansenParams; onapply: (p: JansenParams) => void } = $props();

let objective = $state<"flat" | "highstep">("flat");
let seed = $state(1);
let generations = $state(80);
let population = $state(60);
let running = $state(false);
let history = $state<GAState[]>([]);
let worker: Worker | null = null;

const last = $derived(history.at(-1));

function start() {
	stop();
	history = [];
	worker = new Worker(new URL("./ga.worker.ts", import.meta.url), {
		type: "module",
	});
	worker.onmessage = (e) => {
		if (e.data.type === "state") history = [...history, e.data.state];
		else running = false;
	};
	running = true;
	const req: WorkerRequest = {
		start: paramsToGenome(params),
		objective,
		seed,
		generations,
		population,
	};
	worker.postMessage(req);
}

function stop() {
	worker?.terminate();
	worker = null;
	running = false;
}

const chart = $derived.by(() => {
	const f = history.filter((h) => Number.isFinite(h.bestFitness));
	if (f.length < 2) return { best: "", mean: "" };
	const vals = f.flatMap((h) => [
		h.bestFitness,
		Number.isFinite(h.meanFitness) ? h.meanFitness : h.bestFitness,
	]);
	const lo = Math.min(...vals);
	const hi = Math.max(...vals);
	const pt = (i: number, v: number) =>
		`${(i / Math.max(generations, 1)) * 300},${100 - ((v - lo) / (hi - lo || 1)) * 90 - 5}`;
	return {
		best: f.map((h, i) => pt(i, h.bestFitness)).join(" "),
		mean: f
			.map((h, i) =>
				pt(i, Number.isFinite(h.meanFitness) ? h.meanFitness : h.bestFitness),
			)
			.join(" "),
	};
});
</script>

<div class="evolver">
	<div class="row">
		<label>目标
			<select bind:value={objective}>
				<option value="flat">平地行走（长而平的着地段）</option>
				<option value="highstep">越障（高抬腿）</option>
			</select>
		</label>
		<label>种子 <input type="number" bind:value={seed} min="0" /></label>
		<label>代数 <input type="number" bind:value={generations} min="1" max="500" /></label>
		<label>种群 <input type="number" bind:value={population} min="10" max="300" /></label>
		{#if running}
			<button onclick={stop}>停止</button>
		{:else}
			<button onclick={start}>从当前参数开始演化</button>
		{/if}
	</div>
	<svg viewBox="0 0 300 100" class="chart">
		<polyline points={chart.mean} fill="none" stroke="#8888" stroke-width="1.5" />
		<polyline points={chart.best} fill="none" stroke="#e5733f" stroke-width="2" />
	</svg>
	{#if last}
		<p>第 {last.generation} / {generations} 代 · 最优适应度 {last.bestFitness.toFixed(3)}（橙）· 种群均值（灰）</p>
		<button onclick={() => onapply(genomeToParams(last.best))}>把当前最优载入上方查看</button>
	{/if}
</div>

<style>
	.evolver { display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
	.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; }
	.row input[type="number"] { width: 70px; }
	.evolver > button { align-self: flex-start; }
	.chart { width: 100%; max-width: 480px; height: 120px; border: 1px solid #8884; border-radius: 8px; }
</style>
