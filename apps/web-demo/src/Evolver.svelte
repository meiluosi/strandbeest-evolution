<script lang="ts">
import {
	type GAState,
	genomeSpace,
	type LinkageSpec,
	trace,
} from "strandbeest-core";
import { onDestroy } from "svelte";
import type { WorkerRequest } from "./ga.worker";
import Icon from "./Icon.svelte";
import { t } from "./i18n/index.svelte";
import MetricStrip from "./MetricStrip.svelte";
import StateBadge from "./StateBadge.svelte";

let {
	spec,
	onapply,
}: { spec: LinkageSpec; onapply: (s: LinkageSpec) => void } = $props();

type RunStatus = "idle" | "running" | "stopped" | "done" | "error";
const STATUS_KEYS = {
	idle: "evolve.status.idle",
	running: "evolve.status.running",
	stopped: "evolve.status.stopped",
	done: "evolve.status.done",
	error: "evolve.status.error",
} as const;
const EMPTY_KEYS = {
	idle: "evolve.empty.idle",
	running: "evolve.empty.running",
	stopped: "evolve.empty.stopped",
	done: "evolve.empty.done",
	error: "evolve.empty.error",
} as const;
type WorkerResponse =
	| { type: "state"; state: GAState; kernel: string }
	| { type: "done" | "stopped"; kernel?: string }
	| { type: "error"; message: string; kernel?: string };
type ChartPoint = { x: number; y: number; generation: number; value: number };

let objective = $state<"flat" | "highstep">("flat");
let seed = $state(1);
let generations = $state(80);
let population = $state(60);
let status = $state<RunStatus>("idle");
let history = $state<GAState[]>([]);
let run = $state<WorkerRequest | null>(null);
let worker: Worker | null = null;
let requestId = 0;
let error = $state("");

const running = $derived(status === "running");
const last = $derived(history.at(-1));
const runGenerations = $derived(run?.generations ?? generations);
const statusTone = $derived(
	status === "running"
		? "accent"
		: status === "done"
			? "success"
			: status === "stopped" || status === "error"
				? "danger"
				: "neutral",
);

function dispose(target: Worker | null) {
	if (!target) return;
	target.onmessage = null;
	target.onerror = null;
	target.terminate();
	if (worker === target) worker = null;
}

function fail(message: string, target: Worker | null = null) {
	error = t("evolve.failed", { message });
	status = "error";
	dispose(target ?? worker);
}

function start() {
	if (running) return;
	requestId++;
	const id = requestId;
	dispose(worker);
	history = [];
	error = "";
	const request: WorkerRequest = {
		spec: $state.snapshot(spec) as LinkageSpec,
		objective,
		seed,
		generations,
		population,
	};
	run = request;
	status = "running";
	try {
		const next = new Worker(new URL("./ga.worker.ts", import.meta.url), {
			type: "module",
		});
		worker = next;
		next.onmessage = (event: MessageEvent<WorkerResponse>) => {
			if (id !== requestId || worker !== next || status !== "running") return;
			const message = event.data;
			if (message.type === "state") history = [...history, message.state];
			else if (message.type === "error") fail(message.message, next);
			else if (message.type === "done") {
				status = "done";
				dispose(next);
			}
		};
		next.onerror = (event) => {
			event.preventDefault();
			if (id !== requestId || worker !== next || status !== "running") return;
			fail(event.message, next);
		};
		next.postMessage(request);
	} catch (cause) {
		if (id !== requestId) return;
		fail(cause instanceof Error ? cause.message : String(cause));
	}
}

function stop() {
	if (!running) return;
	requestId++;
	dispose(worker);
	status = "stopped";
}

onDestroy(() => {
	requestId++;
	dispose(worker);
});

function formatFitness(value: number | undefined): string {
	return value !== undefined && Number.isFinite(value) ? value.toFixed(6) : "—";
}

const runMetricItems = $derived(
	last && run
		? [
				{
					key: "generation",
					label: t("evolve.currentGeneration"),
					value: String(last.generation),
					detail: `/ ${run.generations}`,
					valueClass: "generation-value",
				},
				{
					key: "best",
					label: t("evolve.bestFitness"),
					value: formatFitness(last.bestFitness),
					valueClass: "best-fitness",
				},
				{
					key: "mean",
					label: t("evolve.meanFitness"),
					value: formatFitness(last.meanFitness),
					valueClass: "mean-fitness",
				},
			]
		: [],
);

const bestSpec = $derived(
	last && run ? genomeSpace(run.spec).toSpec(last.best) : null,
);
const canApply = $derived(
	bestSpec !== null &&
		Object.entries(bestSpec.params).some(
			([key, value]) => spec.params[key] !== value,
		),
);

const paths = $derived.by(() => {
	if (!last || !run) return null;
	const before = trace(run.spec, 90).foot;
	const best = trace(genomeSpace(run.spec).toSpec(last.best), 90).foot;
	const all = [...before, ...best];
	if (!all.length) return null;
	const xs = all.map((point) => point.x);
	const ys = all.map((point) => point.y);
	const x0 = Math.min(...xs);
	const y0 = Math.min(...ys);
	const scale = Math.min(
		520 / (Math.max(...xs) - x0 || 1),
		150 / (Math.max(...ys) - y0 || 1),
	);
	const points = (path: typeof before) =>
		path
			.map(
				(point) =>
					`${20 + (point.x - x0) * scale},${170 - (point.y - y0) * scale}`,
			)
			.join(" ");
	return { before: points(before), best: points(best) };
});

const chart = $derived.by(() => {
	const bestStates = history.filter((state) =>
		Number.isFinite(state.bestFitness),
	);
	const meanStates = history.filter((state) =>
		Number.isFinite(state.meanFitness),
	);
	const values = [
		...bestStates.map((state) => state.bestFitness),
		...meanStates.map((state) => state.meanFitness),
	];
	if (!values.length) return null;
	const lo = Math.min(...values);
	const hi = Math.max(...values);
	const point = (state: GAState, value: number): ChartPoint => ({
		x: 46 + (state.generation / Math.max(runGenerations, 1)) * 574,
		y: 166 - ((value - lo) / (hi - lo || 1)) * 142,
		generation: state.generation,
		value,
	});
	return {
		lo,
		hi,
		best: bestStates.map((state) => point(state, state.bestFitness)),
		mean: meanStates.map((state) => point(state, state.meanFitness)),
	};
});

const pointString = (points: ChartPoint[]) =>
	points.map((point) => `${point.x},${point.y}`).join(" ");

function applyBest() {
	if (!bestSpec || !canApply) return;
	onapply(bestSpec);
}
</script>

<div class="evolver">
	<div class="run-layout">
		<form class="evolve-panel config-panel" onsubmit={(event) => { event.preventDefault(); start(); }}>
			<header class="panel-title">
				<span class="eyebrow">{t("evolve.configEyebrow")}</span>
				<h3>{t("evolve.configTitle")}</h3>
				<p>{t("evolve.configNote")}</p>
			</header>
			<fieldset class="config-fields" disabled={running}>
				<label>{t("evolve.objective")}
					<select bind:value={objective}>
						<option value="flat">{t("evolve.objective.flat")}</option>
						<option value="highstep">{t("evolve.objective.obstacle")}</option>
					</select>
				</label>
				<div class="config-pair">
					<label>{t("evolve.seed")}<input type="number" bind:value={seed} min="0" step="1" required /></label>
					<label>{t("evolve.population")}<input type="number" bind:value={population} min="10" max="300" step="1" required /></label>
				</div>
				<label>{t("evolve.generations")}<input type="number" bind:value={generations} min="1" max="500" step="1" required /></label>
			</fieldset>
			<p class="scope-note">{t("evolve.searchScope")}</p>
			{#if running}
				<button class="btn run-control" type="button" onclick={stop}>{t("common.stop")}</button>
			{:else}
				<button class="btn primary run-control" type="submit">{t("evolve.start")}</button>
			{/if}
		</form>

		<section class="evolve-panel run-panel" aria-label={t("evolve.runPanel")}>
			<header class="run-heading">
				<div>
					<span class="eyebrow">{t("evolve.runEyebrow")}</span>
					<h3>{t("evolve.runTitle")}</h3>
				</div>
				<StateBadge
					label={t(STATUS_KEYS[status])}
					tone={statusTone}
					state={status}
					live={true}
					className="run-status {status}"
				/>
			</header>
			{#if error}<p class="notice error" role="alert">{error}</p>{/if}
			{#if last && run}
				<MetricStrip
					items={runMetricItems}
					label={t("evolve.runPanel")}
					variant="run"
				/>
				<div class="generation-progress">
					<progress max={run.generations} value={last.generation} aria-label={t("evolve.progressAria")}></progress>
					<small>{t("evolve.runSummary", { generation: last.generation, generations: run.generations, population: run.population, seed: run.seed })}</small>
				</div>
			{:else}
				<div class="run-empty">
					<span class="empty-run-icon"><Icon name="evolve" /></span>
					<strong>{t(EMPTY_KEYS[status])}</strong>
					<p>{t("evolve.emptyHint")}</p>
				</div>
			{/if}
		</section>
	</div>

	{#if last && run}
		<footer class="apply-bar">
			<span>{canApply ? t("evolve.applyNote") : t("evolve.noChanges")}</span>
			<button class="btn primary" disabled={!canApply} onclick={applyBest}>{t("evolve.loadBest")}</button>
		</footer>
	{/if}

	<div class="analysis-grid">
		<section class="evolve-panel fitness-panel">
			<header class="panel-title">
				<h3>{t("evolve.chartTitle")}</h3>
				<p>{t("evolve.chartNote")}</p>
			</header>
			{#if chart}
				<svg viewBox="0 0 640 200" class="fitness-chart" role="img" aria-label={t("evolve.chartAria")}>
					<title>{t("evolve.chartAria")}</title>
					<line x1="46" y1="24" x2="620" y2="24" class="chart-grid" />
					<line x1="46" y1="95" x2="620" y2="95" class="chart-grid" />
					<line x1="46" y1="166" x2="620" y2="166" class="chart-grid" />
					<text x="40" y="28" text-anchor="end">{chart.hi.toFixed(3)}</text>
					<text x="40" y="170" text-anchor="end">{chart.lo.toFixed(3)}</text>
					<text x="46" y="190">0</text>
					<text x="620" y="190" text-anchor="end">{runGenerations}</text>
					<polyline points={pointString(chart.mean)} class="mean-line" />
					<polyline points={pointString(chart.best)} class="best-line" />
					{#if chart.best.at(-1)}<circle cx={chart.best.at(-1)?.x} cy={chart.best.at(-1)?.y} r="3" class="best-point" />{/if}
					{#if chart.mean.at(-1)}<circle cx={chart.mean.at(-1)?.x} cy={chart.mean.at(-1)?.y} r="2.5" class="mean-point" />{/if}
				</svg>
				<div class="chart-legend"><span><i class="best-key"></i>{t("evolve.bestFitness")}</span><span><i class="mean-key"></i>{t("evolve.meanFitness")}</span></div>
			{:else}
				<p class="chart-empty">{t("evolve.chartEmpty")}</p>
			{/if}
		</section>

		<section class="evolve-panel paths-panel">
			<header class="panel-title">
				<h3>{t("evolve.pathsTitle")}</h3>
				<p>{t("evolve.pathsNote")}</p>
			</header>
			{#if paths}
				<svg viewBox="0 0 560 190" class="path-chart" role="img" aria-label={t("evolve.pathsAria")}>
					<title>{t("evolve.pathsAria")}</title>
					{#if paths.before}<polygon points={paths.before} class="path-before" />{/if}
					{#if paths.best}<polygon points={paths.best} class="path-best" />{/if}
				</svg>
				<small>{t("evolve.pathsLegend")}</small>
			{:else}
				<p class="chart-empty">{t("evolve.pathsEmpty")}</p>
			{/if}
		</section>
	</div>
</div>

<style>
	.evolver { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
	.run-layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 16px; align-items: stretch; }
	.analysis-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 16px; }
	.evolve-panel { min-width: 0; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-md); box-shadow: var(--shadow-sm); }
	.config-panel { display: flex; flex-direction: column; padding: 18px; }
	.panel-title { margin-bottom: 15px; }
	.panel-title h3, .run-heading h3 { margin: 3px 0; font-size: 15px; }
	.panel-title p { margin: 0; color: var(--text-muted); font-size: 11px; line-height: 1.55; }
	.eyebrow { color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; font-weight: 600; letter-spacing: 0.12em; }
	.config-fields { display: flex; flex-direction: column; gap: 13px; min-width: 0; margin: 0; padding: 0; border: 0; }
	.config-fields label { width: 100%; color: var(--text-soft); }
	.config-fields input, .config-fields select { width: 100%; min-height: 38px; margin-top: 4px; }
	.config-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
	.scope-note { margin: 14px 0; padding: 10px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--surface-inset); color: var(--text-muted); font-size: 10px; line-height: 1.6; }
	.run-control { width: 100%; margin-top: auto; }
	.run-panel { display: flex; flex-direction: column; padding: 18px; }
	.run-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
	.generation-progress { margin-top: auto; }
	progress { display: block; width: 100%; height: 7px; border: 0; border-radius: 999px; overflow: hidden; background: var(--surface-muted); accent-color: var(--accent); }
	progress::-webkit-progress-bar { background: var(--surface-muted); }
	progress::-webkit-progress-value { background: var(--accent); }
	progress::-moz-progress-bar { background: var(--accent); }
	.generation-progress small { display: block; margin-top: 8px; }
	.run-empty { flex: 1; min-height: 190px; display: grid; align-content: center; justify-items: center; text-align: center; color: var(--text-muted); }
	.empty-run-icon { display: grid; place-items: center; width: 42px; height: 42px; margin-bottom: 12px; border: 1px solid var(--line); border-radius: 50%; background: var(--surface-inset); color: var(--text-faint); }
	.empty-run-icon :global(svg) { width: 19px; height: 19px; }
	.run-empty strong { color: var(--text-soft); font-weight: 500; }
	.run-empty p { max-width: 420px; margin-bottom: 0; font-size: 11px; line-height: 1.6; }
	.fitness-panel, .paths-panel { padding: 18px; }
	.fitness-chart, .path-chart { width: 100%; height: auto; border-radius: var(--radius-sm); background: var(--canvas-bg); }
	.chart-grid { stroke: var(--grid-line); stroke-width: 1; }
	.fitness-chart text { fill: var(--text-muted); font-family: var(--font-mono); font-size: 9px; }
	.best-line, .mean-line, .path-before, .path-best { fill: none; vector-effect: non-scaling-stroke; }
	.best-line { stroke: var(--accent); stroke-width: 2; }
	.mean-line { stroke: var(--blue); stroke-width: 1.5; }
	.best-point { fill: var(--accent); }
	.mean-point { fill: var(--blue); }
	.chart-legend { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 10px; color: var(--text-muted); font-size: 11px; }
	.chart-legend span { display: inline-flex; align-items: center; gap: 6px; }
	.chart-legend i { width: 18px; height: 2px; }
	.best-key { background: var(--accent); }
	.mean-key { background: var(--blue); }
	.path-before { stroke: var(--text-muted); stroke-width: 1.5; stroke-dasharray: 5 4; }
	.path-best { fill: color-mix(in srgb, var(--accent) 10%, transparent); stroke: var(--accent); stroke-width: 2; }
	.paths-panel > small { display: block; margin-top: 10px; }
	.chart-empty { min-height: 190px; display: grid; place-items: center; margin: 0; padding: 24px; border-radius: var(--radius-sm); background: var(--canvas-bg); color: var(--text-muted); text-align: center; }
	.apply-bar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 16px; border: 1px solid var(--line); border-left: 3px solid var(--accent); border-radius: var(--radius-md); background: var(--surface); }
	.apply-bar span { color: var(--text-muted); font-size: 11px; line-height: 1.55; }
	.apply-bar .btn { flex: 0 0 auto; }
	@media (max-width: 1120px) {
		.run-layout { grid-template-columns: 250px minmax(0, 1fr); gap: 12px; }
		.analysis-grid { grid-template-columns: minmax(0, 1fr); gap: 12px; }
	}
	@media (max-width: 820px) {
		.run-layout { grid-template-columns: minmax(0, 1fr); }
		.config-fields { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
		.config-fields > label:first-child { grid-column: 1 / -1; }
		.run-control { margin-top: 4px; }
	}
	@media (max-width: 520px) {
		.config-panel, .run-panel, .fitness-panel, .paths-panel { padding: 14px; }
		.config-fields { display: flex; }
		.run-empty { min-height: 150px; }
		.apply-bar { align-items: stretch; flex-direction: column; }
		.apply-bar .btn { width: 100%; }
	}
</style>
