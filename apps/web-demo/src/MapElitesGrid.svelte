<script lang="ts">
import type { Design } from "strandbeest-core";
import { download } from "./api";
import {
	type AtlasDoc,
	AtlasValidationError,
	atlasSlice,
	bestAtlasCell,
	type EliteCellData,
	eliteDesign,
	eliteFeature,
	evolveAtlas,
	FEATURE_KEYS,
	parseAtlas,
} from "./atlas";
import { currentDesign, openDocument } from "./editor.svelte";
import { t } from "./i18n/index.svelte";
import defaultAtlasRaw from "./sample-atlas.json";
import { STATIC } from "./static";

let {
	atlas: inputAtlas = null,
	selectedCell = null,
	onselect,
	onload,
}: {
	atlas?: AtlasDoc | null;
	selectedCell?: number[] | null;
	onselect?: (elite: EliteCellData) => void;
	onload?: (design: Design) => void;
} = $props();

const defaultAtlas = parseAtlas(defaultAtlasRaw);
let customAtlas = $state<AtlasDoc | null>(null);
const activeAtlas = $derived(customAtlas ?? inputAtlas ?? defaultAtlas);
let running = $state(false);
let runProgress = $state(0);
let runError = $state<string | null>(null);
let hoveredCoord = $state<number[] | null>(null);
let hoveredElite = $state<EliteCellData | null>(null);
let internalSelected = $state<number[] | null>(null);
let sliceTail = $state<number[]>([]);
const selectedCoord = $derived(internalSelected ?? selectedCell);

$effect(() => {
	const best = bestAtlasCell(activeAtlas);
	sliceTail =
		best?.cell.slice(2) ?? activeAtlas.grid_shape.slice(2).map(() => 0);
	internalSelected = null;
	hoveredCoord = null;
	hoveredElite = null;
});

const visibleCells = $derived(atlasSlice(activeAtlas, sliceTail));
const cellMap = $derived(
	new Map(visibleCells.map((elite) => [elite.cell.join(","), elite])),
);
const selectedElite = $derived(
	selectedCoord ? (cellMap.get(selectedCoord.join(",")) ?? null) : null,
);
const paretoSet = $derived(
	new Set((activeAtlas.pareto_front ?? []).map((coord) => coord.join(","))),
);
const nx = $derived(activeAtlas.grid_shape[0] ?? 1);
const ny = $derived(activeAtlas.grid_shape[1] ?? 1);
const minFitness = $derived(
	activeAtlas.cells.length
		? Math.min(...activeAtlas.cells.map((c) => c.fitness))
		: 0,
);
const maxFitness = $derived(
	activeAtlas.cells.length
		? Math.max(...activeAtlas.cells.map((c) => c.fitness))
		: 1,
);
const rangeX = $derived(
	activeAtlas.feature_ranges?.[activeAtlas.features[0] ?? ""] ?? [0, nx],
);
const rangeY = $derived(
	activeAtlas.feature_ranges?.[activeAtlas.features[1] ?? ""] ?? [0, ny],
);
const rx0 = $derived(rangeX[0] ?? 0);
const rx1 = $derived(rangeX[1] ?? nx);
const ry0 = $derived(rangeY[0] ?? 0);
const ry1 = $derived(rangeY[1] ?? ny);

function featureLabel(name: string): string {
	return FEATURE_KEYS[name]
		? t(FEATURE_KEYS[name])
		: t("map_elites.featureName", { name });
}
function axisLabel(index: number): string {
	const name = activeAtlas.features[index] ?? "";
	const label = featureLabel(name);
	return activeAtlas.feature_ranges?.[name]
		? label
		: t("map_elites.binAxis", { name: label });
}
function sliceLabel(axis: number, bin: number): string {
	const range = activeAtlas.feature_ranges?.[activeAtlas.features[axis] ?? ""];
	if (!range) return t("map_elites.binIndex", { index: bin });
	const width = (range[1] - range[0]) / (activeAtlas.grid_shape[axis] ?? 1);
	return t("map_elites.binRange", {
		index: bin,
		lo: (range[0] + bin * width).toFixed(3),
		hi: (range[0] + (bin + 1) * width).toFixed(3),
	});
}
function setSlice(axis: number, value: number) {
	sliceTail = activeAtlas.grid_shape
		.slice(2)
		.map((_, i) => (i === axis ? value : (sliceTail[i] ?? 0)));
	internalSelected = null;
	handleCellLeave();
}
function selectBest() {
	const best = bestAtlasCell(activeAtlas);
	if (!best) return;
	sliceTail = best.cell.slice(2);
	internalSelected = [...best.cell];
	onselect?.(best);
	handleCellLeave();
}
function displayError(error: unknown): string {
	return error instanceof AtlasValidationError
		? t("map_elites.invalidAtlas", { field: error.field })
		: error instanceof Error
			? error.message
			: String(error);
}
// Color mapping: low -> blue/teal -> amber -> red/gold
function fitnessColor(fitness: number): string {
	const span = maxFitness - minFitness;
	const tNorm =
		span > 1e-6 ? Math.max(0, Math.min(1, (fitness - minFitness) / span)) : 0.5;

	if (tNorm < 0.25) {
		const s = tNorm / 0.25;
		const r = Math.round(20 + s * (14 - 20));
		const g = Math.round(40 + s * (120 - 40));
		const b = Math.round(80 + s * (160 - 80));
		return `rgb(${r}, ${g}, ${b})`;
	}
	if (tNorm < 0.5) {
		const s = (tNorm - 0.25) / 0.25;
		const r = Math.round(14 + s * (16 - 14));
		const g = Math.round(120 + s * (185 - 120));
		const b = Math.round(160 + s * (129 - 160));
		return `rgb(${r}, ${g}, ${b})`;
	}
	if (tNorm < 0.75) {
		const s = (tNorm - 0.5) / 0.25;
		const r = Math.round(16 + s * (245 - 16));
		const g = Math.round(185 + s * (158 - 185));
		const b = Math.round(129 + s * (11 - 129));
		return `rgb(${r}, ${g}, ${b})`;
	}
	const s = (tNorm - 0.75) / 0.25;
	const r = Math.round(245 + s * (251 - 245));
	const g = Math.round(158 + s * (191 - 158));
	const b = Math.round(11 + s * (36 - 11));
	return `rgb(${r}, ${g}, ${b})`;
}

// SVG layout dimensions
const SVG_W = 540;
const SVG_H = 400;
const PAD_L = 50;
const PAD_R = 30;
const PAD_T = 20;
const PAD_B = 45;

const PLOT_W = SVG_W - PAD_L - PAD_R;
const PLOT_H = SVG_H - PAD_T - PAD_B;

const cellW = $derived(PLOT_W / Math.max(1, nx));
const cellH = $derived(PLOT_H / Math.max(1, ny));

function handleCellClick(coord: number[], elite: EliteCellData | null) {
	internalSelected = coord;
	if (elite) onselect?.(elite);
}
function handleCellEnter(coord: number[], elite: EliteCellData | null) {
	hoveredCoord = coord;
	hoveredElite = elite;
}
function handleCellLeave() {
	hoveredCoord = null;
	hoveredElite = null;
}
function loadViewerCurrent() {
	if (!selectedElite?.design) return;
	try {
		const doc = eliteDesign(selectedElite);
		if (!doc) return;
		if (onload) onload(doc);
		else openDocument(doc);
		runError = null;
	} catch (error) {
		runError = displayError(error);
	}
}
function exportAtlasJson() {
	download(
		`species-atlas-${activeAtlas.id}.json`,
		JSON.stringify(activeAtlas, null, 2),
	);
}
async function importAtlasJson(e: Event) {
	const input = e.target as HTMLInputElement;
	const file = input.files?.[0];
	if (!file) return;
	try {
		customAtlas = parseAtlas(JSON.parse(await file.text()));
		runError = null;
	} catch (error) {
		runError =
			error instanceof SyntaxError
				? t("map_elites.invalidJson")
				: displayError(error);
	} finally {
		input.value = "";
	}
}
async function triggerQdEvolution() {
	if (STATIC || running) return;
	running = true;
	runProgress = 0;
	runError = null;
	try {
		customAtlas = await evolveAtlas(structuredClone(currentDesign()), (job) => {
			if (job.progress?.total > 0)
				runProgress = Math.round(
					(job.progress.done / job.progress.total) * 100,
				);
		});
	} catch (error) {
		runError = displayError(error);
	} finally {
		running = false;
	}
}
</script>

<div class="qd-container">
	<div class="qd-header">
		<div class="qd-title-area">
			<h3>{t("map_elites.title")}</h3>
			<p class="qd-subtitle">{t("map_elites.subtitle")}</p>
		</div>
		<div class="qd-actions">
			{#if !STATIC}
				<button class="btn primary" disabled={running} onclick={triggerQdEvolution}>
					{running ? t("map_elites.running", { pct: runProgress }) : t("map_elites.runQd")}
				</button>
			{/if}
			<button class="btn" onclick={exportAtlasJson}>{t("map_elites.exportAtlas")}</button>
			<label class="btn inline-btn" style="cursor:pointer">
				{t("map_elites.importAtlas")}
				<input type="file" accept="application/json" onchange={importAtlasJson} hidden />
			</label>
		</div>
	</div>

	{#if runError}
		<p class="notice error">{runError}</p>
	{/if}

	<!-- Statistics summary row -->
	<div class="qd-stats-bar">
		<div class="stat-pill">
			<span class="stat-label">{t("map_elites.qdScore")}</span>
			<span class="stat-value">{activeAtlas.qd_score?.toFixed(2) ?? "0.00"}</span>
		</div>
		<div class="stat-pill">
			<span class="stat-label">{t("map_elites.coverage")}</span>
			<span class="stat-value">
				{((activeAtlas.coverage ?? 0) * 100).toFixed(1)}%
				<small>({activeAtlas.cells_filled ?? 0}/{activeAtlas.cells_total ?? 0})</small>
			</span>
		</div>
		<div class="stat-pill">
			<span class="stat-label">{t("map_elites.bestFitness")}</span>
			<span class="stat-value highlight">{activeAtlas.best_fitness?.toFixed(3) ?? "-"}</span>
		</div>
		<div class="stat-pill">
			<span class="stat-label">{t("map_elites.evaluations")}</span>
			<span class="stat-value">{activeAtlas.evals ?? 0}</span>
		</div>
		<div class="stat-pill">
			<span class="stat-label">{t("map_elites.paretoFront")}</span>
			<span class="stat-value pareto-val">{activeAtlas.pareto_front?.length ?? 0}</span>
		</div>
	</div>

 <div class="row center">
  {#each activeAtlas.grid_shape.slice(2) as size, i}
   <label>{t("map_elites.slice", { feature: featureLabel(activeAtlas.features[i + 2] ?? "") })}
    <select value={sliceTail[i] ?? 0} onchange={(event) => setSlice(i, Number(event.currentTarget.value))}>
     {#each Array(size) as _, bin}<option value={bin}>{sliceLabel(i + 2, bin)}</option>{/each}
    </select>
   </label>
  {/each}
  <button class="btn" disabled={!activeAtlas.cells.length} onclick={selectBest}>{t("map_elites.showBest")}</button>
  <small>{t("map_elites.sliceCount", { visible: visibleCells.length, total: activeAtlas.cells.length })}</small>
 </div>
	<!-- Main 2D Heatmap Grid Display -->
	<div class="grid-layout">
		<div class="svg-wrapper">
			<svg viewBox="0 0 {SVG_W} {SVG_H}" class="qd-heatmap-svg" role="group" aria-label={t("map_elites.gridLabel")}>
				<!-- Background plotting area -->
				<rect
					x={PAD_L}
					y={PAD_T}
					width={PLOT_W}
					height={PLOT_H}
					fill="#090d16"
					stroke="#1e293b"
					stroke-width="1"
				/>

				<!-- Grid Cells -->
				{#each Array(ny) as _, yIdx}
					{@const y = ny - 1 - yIdx} <!-- Y=0 at bottom -->
					{#each Array(nx) as _, x}
						{@const coord = [x, y, ...sliceTail]}
						{@const key = coord.join(",")}
						{@const elite = cellMap.get(key) ?? null}
						{@const isFilled = elite !== null}
						{@const isPareto = paretoSet.has(key)}
						{@const isSelected = selectedCoord?.join(",") === key}
						{@const isHovered = hoveredCoord?.join(",") === key}
						{@const cx = PAD_L + x * cellW}
						{@const cy = PAD_T + yIdx * cellH}

						
						<g
							class="cell-group"
							role="button"
							tabindex="0"
							aria-label={t("map_elites.cellCoordinates", { coordinates: coord.join(", ") })}
							onmouseenter={() => handleCellEnter(coord, elite)}
							onmouseleave={handleCellLeave}
							onclick={() => handleCellClick(coord, elite)}
							onkeydown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); handleCellClick(coord, elite); } }}
						>
							<rect
								x={cx + 0.75}
								y={cy + 0.75}
								width={Math.max(1, cellW - 1.5)}
								height={Math.max(1, cellH - 1.5)}
								rx="2"
								fill={isFilled ? fitnessColor(elite.fitness) : "#131a29"}
								stroke={isSelected ? "#ffffff" : isHovered ? "#38bdf8" : isPareto ? "#f59e0b" : "#1f293d"}
								stroke-width={isSelected ? 2.5 : isHovered ? 2 : isPareto ? 1.5 : 0.75}
							/>

							{#if isPareto}
								<!-- Pareto optimal indicator diamond -->
								<polygon
									points="{cx + cellW / 2},{cy + cellH / 2 - 3.5} {cx + cellW / 2 + 3.5},{cy + cellH / 2} {cx + cellW / 2},{cy + cellH / 2 + 3.5} {cx + cellW / 2 - 3.5},{cy + cellH / 2}"
									fill="#fbbf24"
									stroke="#78350f"
									stroke-width="0.5"
									pointer-events="none"
								/>
							{/if}
						</g>
					{/each}
				{/each}

				<!-- X Axis ticks & label -->
				<text
					x={PAD_L + PLOT_W / 2}
					y={SVG_H - 8}
					text-anchor="middle"
					class="axis-title"
				>
					{axisLabel(0)}
				</text>

				<text x={PAD_L} y={SVG_H - 24} text-anchor="start" class="axis-tick">
					{rx0.toFixed(2)}
				</text>
				<text x={PAD_L + PLOT_W / 2} y={SVG_H - 24} text-anchor="middle" class="axis-tick">
					{((rx0 + rx1) / 2).toFixed(2)}
				</text>
				<text x={PAD_L + PLOT_W} y={SVG_H - 24} text-anchor="end" class="axis-tick">
					{rx1.toFixed(2)}
				</text>

				<!-- Y Axis ticks & label -->
				<g transform="translate(14, {PAD_T + PLOT_H / 2}) rotate(-90)">
					<text text-anchor="middle" class="axis-title">{axisLabel(1)}</text>
				</g>

				<text x={PAD_L - 6} y={PAD_T + PLOT_H} text-anchor="end" class="axis-tick">
					{ry0.toFixed(2)}
				</text>
				<text x={PAD_L - 6} y={PAD_T + PLOT_H / 2 + 4} text-anchor="end" class="axis-tick">
					{((ry0 + ry1) / 2).toFixed(2)}
				</text>
				<text x={PAD_L - 6} y={PAD_T + 10} text-anchor="end" class="axis-tick">
					{ry1.toFixed(2)}
				</text>
			</svg>

			<!-- Colormap colorbar legend -->
			<div class="colorbar-legend">
				<span class="legend-tick">{minFitness.toFixed(2)}</span>
				<div class="colorbar-gradient"></div>
				<span class="legend-tick">{maxFitness.toFixed(2)}</span>
				<div class="legend-pareto">
					<span class="pareto-diamond">◆</span>
					<span class="legend-text">{t("map_elites.paretoFront")}</span>
				</div>
			</div>
		</div>

		<!-- Hover & Selection Inspector HUD -->
		<div class="qd-inspector">
			{#if hoveredCoord}
				{@const elite = hoveredElite}
				{@const isPareto = paretoSet.has(hoveredCoord.join(","))}
				<div class="hud-card hover-card">
					<div class="hud-header">
						<h4>{t("map_elites.cellCoordinates", { coordinates: hoveredCoord.join(", ") })}</h4>
						{#if isPareto}
							<span class="badge pareto-badge">{t("map_elites.paretoBadge")}</span>
						{/if}
					</div>
					{#if elite}
						<div class="hud-metrics">
							<div class="metric-row">
								<span>{t("map_elites.fitness", { value: elite.fitness.toFixed(3) })}</span>
							</div>
       {#each activeAtlas.features as feature}
        <div class="metric-row"><span>{featureLabel(feature)}: {eliteFeature(elite, feature)?.toFixed(3) ?? "—"}</span></div>
       {/each}
							<div class="metric-row sub">
								<span>{t("map_elites.legs", { n: elite.legs ?? 6 })}</span>
								<span>{t("map_elites.born", { n: elite.born })}</span>
							</div>
						</div>
					{:else}
						<p class="muted">{t("map_elites.emptyCell")}</p>
					{/if}
				</div>
			{:else}
				<div class="hud-card hover-card placeholder">
					<p class="muted">{t("map_elites.selectHint")}</p>
				</div>
			{/if}

			{#if selectedElite}
				{@const sel = selectedElite}
				{@const isSelPareto = selectedCoord ? paretoSet.has(selectedCoord.join(",")) : false}
				<div class="hud-card select-card">
					<div class="hud-header">
						<h4>{t("map_elites.selectedElite")}</h4>
						{#if isSelPareto}
							<span class="badge pareto-badge">{t("map_elites.paretoBadge")}</span>
						{/if}
					</div>
					<div class="hud-metrics">
						<div class="metric-row">
							<span>{t("map_elites.cellCoordinates", { coordinates: selectedCoord?.join(", ") ?? "" })}</span>
							<strong class="highlight">{t("map_elites.fitness", { value: sel.fitness.toFixed(3) })}</strong>
						</div>
      {#each activeAtlas.features as feature}
       <div class="metric-row"><span>{featureLabel(feature)}: {eliteFeature(sel, feature)?.toFixed(3) ?? "—"}</span></div>
      {/each}
					</div>
					<button class="btn primary load-btn" disabled={!sel.design} onclick={loadViewerCurrent}>
						{t("map_elites.loadViewer")}
					</button>
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	.qd-container {
		display: flex;
		flex-direction: column;
		gap: 14px;
		width: 100%;
		font-family: inherit;
	}

	.qd-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
	}

	.qd-title-area h3 {
		margin: 0;
		font-size: 1.15rem;
		font-weight: 600;
	}

	.qd-subtitle {
		margin: 2px 0 0 0;
		font-size: 0.85rem;
		color: #94a3b8;
	}

	.qd-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.inline-btn {
		display: inline-flex;
		align-items: center;
		margin: 0;
	}

	.qd-stats-bar {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		background: #0f172a;
		border: 1px solid #1e293b;
		border-radius: 8px;
		padding: 8px 14px;
	}

	.stat-pill {
		display: flex;
		flex-direction: column;
		min-width: 90px;
	}

	.stat-label {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #94a3b8;
	}

	.stat-value {
		font-size: 1.05rem;
		font-weight: 600;
		color: #f1f5f9;
	}

	.stat-value small {
		font-size: 0.75rem;
		font-weight: 400;
		color: #64748b;
	}

	.stat-value.highlight {
		color: #38bdf8;
	}

	.stat-value.pareto-val {
		color: #fbbf24;
	}

	.grid-layout {
		display: grid;
		grid-template-columns: 1fr 240px;
		gap: 16px;
		align-items: start;
	}

	@media (max-width: 800px) {
		.grid-layout {
			grid-template-columns: 1fr;
		}
	}

	.svg-wrapper {
		display: flex;
		flex-direction: column;
		gap: 8px;
		background: #020617;
		border: 1px solid #1e293b;
		border-radius: 8px;
		padding: 10px;
	}

	.qd-heatmap-svg {
		width: 100%;
		height: auto;
		display: block;
		user-select: none;
	}

	.cell-group {
		cursor: pointer;
		outline: none;
	}

	.cell-group:hover rect {
		filter: brightness(1.25);
	}

	.axis-title {
		fill: #94a3b8;
		font-size: 11px;
		font-weight: 500;
	}

	.axis-tick {
		fill: #64748b;
		font-size: 10px;
		font-family: monospace;
	}

	.colorbar-legend {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0 10px 4px 10px;
	}

	.colorbar-gradient {
		flex: 1;
		height: 8px;
		border-radius: 4px;
		background: linear-gradient(to right, rgb(20, 40, 80), rgb(14, 120, 160), rgb(16, 185, 129), rgb(245, 158, 11), rgb(251, 191, 36));
	}

	.legend-tick {
		font-size: 0.75rem;
		font-family: monospace;
		color: #94a3b8;
	}

	.legend-pareto {
		display: flex;
		align-items: center;
		gap: 4px;
		margin-left: 12px;
	}

	.pareto-diamond {
		color: #fbbf24;
		font-size: 10px;
	}

	.legend-text {
		font-size: 0.75rem;
		color: #cbd5e1;
	}

	.qd-inspector {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.hud-card {
		background: #0f172a;
		border: 1px solid #1e293b;
		border-radius: 8px;
		padding: 12px;
	}

	.hover-card {
		min-height: 110px;
	}

	.hover-card.placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
		text-align: center;
	}

	.select-card {
		border-color: #0284c7;
		box-shadow: 0 0 10px rgba(2, 132, 199, 0.15);
	}

	.hud-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 8px;
	}

	.hud-header h4 {
		margin: 0;
		font-size: 0.92rem;
		font-weight: 600;
		color: #f8fafc;
	}

	.badge.pareto-badge {
		background: rgba(245, 158, 11, 0.2);
		color: #fbbf24;
		border: 1px solid #d97706;
		padding: 2px 6px;
		border-radius: 4px;
		font-size: 0.7rem;
		font-weight: 500;
	}

	.hud-metrics {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.82rem;
		color: #cbd5e1;
	}

	.metric-row {
		display: flex;
		justify-content: space-between;
	}

	.metric-row.sub {
		color: #94a3b8;
		font-size: 0.75rem;
		margin-top: 2px;
	}

	.metric-row strong.highlight {
		color: #38bdf8;
	}

	.muted {
		color: #64748b;
		font-size: 0.8rem;
		margin: 0;
	}

	.load-btn {
		width: 100%;
		margin-top: 10px;
		font-size: 0.85rem;
		padding: 6px 12px;
	}
</style>
