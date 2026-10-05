<script lang="ts">
import { type GAState, genomeSpace, type LinkageSpec } from "strandbeest-core";
import type { WorkerRequest } from "./ga.worker";
import { t } from "./i18n/index.svelte";

let {
	spec,
	onapply,
}: { spec: LinkageSpec; onapply: (s: LinkageSpec) => void } = $props();

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
		spec: $state.snapshot(spec) as LinkageSpec,
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
		<label>{t("evolve.objective")}
			<select bind:value={objective}>
				<option value="flat">{t("evolve.objective.flat")}</option>
				<option value="highstep">{t("evolve.objective.obstacle")}</option>
			</select>
		</label>
		<label>{t("evolve.seed")} <input type="number" bind:value={seed} min="0" /></label>
		<label>{t("evolve.generations")} <input type="number" bind:value={generations} min="1" max="500" /></label>
		<label>{t("evolve.population")} <input type="number" bind:value={population} min="10" max="300" /></label>
		{#if running}
			<button onclick={stop}>{t("common.stop")}</button>
		{:else}
			<button onclick={start}>{t("evolve.start")}</button>
		{/if}
	</div>
	<svg viewBox="0 0 300 100" class="chart">
		<polyline points={chart.mean} fill="none" stroke="#8888" stroke-width="1.5" />
		<polyline points={chart.best} fill="none" stroke="#e5733f" stroke-width="2" />
	</svg>
	{#if last}
		<p>{t("evolve.progress", { generation: last.generation, generations: generations, bestFitness: last.bestFitness.toFixed(3) })}</p>
		<button onclick={() => onapply(genomeSpace(spec).toSpec(last.best))}>{t("evolve.loadBest")}</button>
	{/if}
</div>


<style>
	.evolver { display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
	.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; }
	.row input[type="number"] { width: 70px; }
	.evolver > button { align-self: flex-start; }
	.chart { width: 100%; max-width: 480px; height: 120px; border: 1px solid #8884; border-radius: 8px; }
</style>