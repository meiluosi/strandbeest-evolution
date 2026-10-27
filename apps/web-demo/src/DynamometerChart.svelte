<script lang="ts">
import {
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	type LinkageSpec,
	quasiStaticSample,
} from "strandbeest-core";
import { t } from "./i18n/index.svelte";

let {
	spec,
	wind = 6,
	mass = 50,
	legs = 12,
	slopeDeg = 0,
	rolling = 5,
	theta = 0,
	onseektheta,
}: {
	spec: LinkageSpec;
	wind?: number;
	mass?: number;
	legs?: number;
	slopeDeg?: number;
	rolling?: number;
	theta?: number;
	onseektheta?: (th: number) => void;
} = $props();

const N_SAMPLES = 120;
const W_SVG = 520;
const H_SVG = 160;
const PAD_L = 45;
const PAD_R = 15;
const PAD_T = 15;
const PAD_B = 25;

const PLOT_W = W_SVG - PAD_L - PAD_R;
const PLOT_H = H_SVG - PAD_T - PAD_B;

// Calculate curves
const data = $derived.by(() => {
	const slopeRad = (slopeDeg * Math.PI) / 180;
	const drag = (rolling / 100) * mass * 9.81;
	const walker = { ...DEFAULT_WALKER, mass, legs };
	const terrain = { slope: slopeRad, drag };

	const thetas: number[] = [];
	const loadTorques: number[] = [];

	for (let i = 0; i < N_SAMPLES; i++) {
		const th = (2 * Math.PI * i) / N_SAMPLES;
		const s = quasiStaticSample(spec, walker, terrain, th);
		thetas.push(th);
		loadTorques.push(s ? s.torque : 0);
	}

	const peakLoad = Math.max(...loadTorques);
	const minLoad = Math.min(...loadTorques);
	const stallIdx = loadTorques.indexOf(peakLoad);
	const stallAngleDeg =
		stallIdx >= 0 ? Math.round((stallIdx / N_SAMPLES) * 360) : 0;

	// Sail available torque at zero crank speed (starting torque)
	const rho = 1.225;
	const aeroFactor =
		DEFAULT_SAIL.gear *
		0.5 *
		rho *
		DEFAULT_SAIL.dragCoeff *
		DEFAULT_SAIL.area *
		DEFAULT_SAIL.radius;
	const sailTorque = aeroFactor * wind * wind;
	const minStartWind = Math.sqrt(Math.max(0, peakLoad) / (aeroFactor || 1));
	const stallMargin = sailTorque - peakLoad;
	const stalls = stallMargin < 0;

	return {
		thetas,
		loadTorques,
		peakLoad,
		minLoad,
		stallIdx,
		stallAngleDeg,
		sailTorque,
		minStartWind,
		stallMargin,
		stalls,
	};
});

// Coordinate scales
const yRange = $derived.by(() => {
	const allY = [...data.loadTorques, data.sailTorque, 0];
	const minY = Math.min(...allY);
	const maxY = Math.max(...allY);
	const span = Math.max(maxY - minY, 1e-4);
	return { min: minY - 0.1 * span, max: maxY + 0.1 * span };
});

const toX = (idx: number) => PAD_L + (idx / (N_SAMPLES - 1)) * PLOT_W;
const toY = (val: number) =>
	PAD_T + (1 - (val - yRange.min) / (yRange.max - yRange.min)) * PLOT_H;

// SVG Path for Load Torque
const loadPath = $derived.by(() => {
	if (!data.loadTorques.length) return "";
	return data.loadTorques
		.map(
			(val, i) =>
				`${i === 0 ? "M" : "L"} ${toX(i).toFixed(1)} ${toY(val).toFixed(1)}`,
		)
		.join(" ");
});

// Horizontal line for sail torque
const sailY = $derived(toY(data.sailTorque));
// Stall marker coordinates
const stallX = $derived(toX(data.stallIdx));
const stallY = $derived(toY(data.peakLoad));
const zeroY = $derived(toY(0));

// Live crank angle cursor
const normTheta = $derived(
	((((theta / (2 * Math.PI)) % 1) + 1) % 1) * (N_SAMPLES - 1),
);
const cursorX = $derived(toX(normTheta));
const cursorIdx = $derived(
	Math.min(N_SAMPLES - 1, Math.max(0, Math.round(normTheta))),
);
const cursorTorque = $derived(data.loadTorques[cursorIdx] ?? 0);
const cursorY = $derived(toY(cursorTorque));

let scrubbing = $state(false);
function pointerToTheta(e: PointerEvent, svg: SVGSVGElement) {
	const r = svg.getBoundingClientRect();
	const frac = Math.max(
		0,
		Math.min(1, (((e.clientX - r.left) / r.width) * W_SVG - PAD_L) / PLOT_W),
	);
	onseektheta?.(frac * 2 * Math.PI);
}
</script>

<div class="dynamometer stack">
	<div class="header">
		<h4>{t("dynamometer.title")}</h4>
		<div class="row center" style="margin:0;gap:6px">
			<button
				class="btn small"
				onclick={() => onseektheta?.((data.stallIdx / N_SAMPLES) * 2 * Math.PI)}
			>
				{t("dynamometer.jumpStall")}
			</button>
			<span class="badge" class:bad={data.stalls} class:good={!data.stalls}>
				{#if data.stalls}
					{t("dynamometer.stalls", { angle: data.stallAngleDeg, minWind: data.minStartWind.toFixed(2) })}
				{:else}
					{t("dynamometer.starts", { margin: (data.stallMargin * 1000).toFixed(1) })}
				{/if}
			</span>
		</div>
	</div>

	<p class="desc">{t("dynamometer.desc")}</p>

	<div class="stats-bar">
		<span class="stat-pill">{t("dynamometer.windSpeed", { wind })}</span>
		<span class="stat-pill">{t("dynamometer.peakTorque", { peak: (data.peakLoad * 1000).toFixed(1) })}</span>
		<span class="stat-pill">{t("dynamometer.minStartWind", { minWind: data.minStartWind.toFixed(2) })}</span>
	</div>

	<div class="chart-container">
		<svg
			role="slider"
			tabindex="0"
			aria-label={t("dynamometer.title")}
			aria-valuemin={0}
			aria-valuemax={360}
			aria-valuenow={Math.round(((((theta * 180) / Math.PI) % 360) + 360) % 360)}
			viewBox="0 0 {W_SVG} {H_SVG}"
			preserveAspectRatio="none"
			style="cursor:crosshair;touch-action:none"
			onkeydown={(e) => {
				if (e.key === "ArrowRight") onseektheta?.(theta + (5 * Math.PI) / 180);
				if (e.key === "ArrowLeft") onseektheta?.(theta - (5 * Math.PI) / 180);
			}}
			onpointerdown={(e) => {
				scrubbing = true;
				e.currentTarget.setPointerCapture(e.pointerId);
				pointerToTheta(e, e.currentTarget);
			}}
			onpointermove={(e) => {
				if (scrubbing) pointerToTheta(e, e.currentTarget);
			}}
			onpointerup={() => (scrubbing = false)}
			onpointercancel={() => (scrubbing = false)}
		>
			<!-- Zero baseline -->
			<line x1={PAD_L} y1={zeroY} x2={W_SVG - PAD_R} y2={zeroY} class="zero-line" />

			<!-- Axes and Grid ticks -->
			{#each [0, 90, 180, 270, 360] as deg, k}
				{@const x = PAD_L + (k / 4) * PLOT_W}
				<line x1={x} y1={PAD_T} x2={x} y2={H_SVG - PAD_B} class="grid-line" />
				<text x={x} y={H_SVG - 8} class="axis-label" text-anchor="middle">{deg}°</text>
			{/each}

			<!-- Y-Axis labels (Min, Zero, Max) -->
			<text x={PAD_L - 6} y={toY(yRange.max) + 4} class="axis-label" text-anchor="end">
				{yRange.max.toFixed(1)} N·m
			</text>
			<text x={PAD_L - 6} y={toY(yRange.min)} class="axis-label" text-anchor="end">
				{yRange.min.toFixed(1)} N·m
			</text>

			<!-- Critical Stall Point Line -->
			<line x1={stallX} y1={PAD_T} x2={stallX} y2={H_SVG - PAD_B} class="stall-line" />

			<!-- Sail Torque Line (Available Wind Drive) -->
			<line x1={PAD_L} y1={sailY} x2={W_SVG - PAD_R} y2={sailY} class="sail-line" />

			<!-- Load Torque Curve T(theta) -->
			<path d={loadPath} class="load-curve" />

			<!-- Live Crank Angle Cursor -->
			<line x1={cursorX} y1={PAD_T} x2={cursorX} y2={H_SVG - PAD_B} class="cursor-line" />
			<circle cx={cursorX} cy={cursorY} r="4.2" class="cursor-dot" />

			<!-- Stall Marker Dot -->
			<circle cx={stallX} cy={stallY} r="4" class="stall-dot" />
		</svg>
	</div>

	<div class="legend">
		<span class="legend-item"><span class="swatch load"></span> {t("dynamometer.loadTorque")}</span>
		<span class="legend-item"><span class="swatch sail"></span> {t("dynamometer.sailTorque")} ({data.sailTorque.toFixed(2)} N·m)</span>
		<span class="legend-item"><span class="swatch stall"></span> {t("dynamometer.stallPoint", { angle: data.stallAngleDeg, peak: (data.peakLoad * 1000).toFixed(1) })}</span>
	</div>
</div>

<style>
	.dynamometer {
		margin-top: 10px;
		padding: 10px;
		background: var(--surface-2, #fbfaf8);
		border: 1px solid var(--border, #e5e3df);
		border-radius: 6px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
	}
	h4 {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
	}
	.desc {
		margin: 0;
		font-size: 12px;
		color: var(--text-muted, #666);
		line-height: 1.4;
	}
	.stats-bar {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.stat-pill {
		font-size: 11px;
		background: var(--surface-1, #fff);
		border: 1px solid var(--border, #e5e3df);
		padding: 2px 6px;
		border-radius: 4px;
		color: var(--text-muted, #555);
	}
	.badge {
		padding: 2px 8px;
		font-size: 12px;
		border-radius: 4px;
		font-weight: 500;
	}
	.badge.good {
		background: #e8f5e9;
		color: #2e7d32;
		border: 1px solid #a5d6a7;
	}
	.badge.bad {
		background: #ffebee;
		color: #c62828;
		border: 1px solid #ef9a9a;
	}
	.chart-container {
		width: 100%;
		height: 160px;
	}
	svg {
		width: 100%;
		height: 100%;
	}
	.zero-line {
		stroke: var(--border, #ccc);
		stroke-dasharray: 2 2;
	}
	.grid-line {
		stroke: var(--border, #eee);
		stroke-width: 1;
	}
	.axis-label {
		font-size: 10px;
		fill: var(--text-muted, #888);
	}
	.load-curve {
		fill: none;
		stroke: #d9622b;
		stroke-width: 2.2;
	}
	.sail-line {
		stroke: #2e7d32;
		stroke-width: 2;
		stroke-dasharray: 4 3;
	}
	.stall-line {
		stroke: #d32f2f;
		stroke-width: 1.5;
		stroke-dasharray: 3 2;
	}
	.stall-dot {
		fill: #d32f2f;
		stroke: white;
		stroke-width: 1.5;
	}
	.cursor-line {
		stroke: var(--blue, #2f6fd1);
		stroke-width: 1.5;
	}
	.cursor-dot {
		fill: var(--blue, #2f6fd1);
		stroke: white;
		stroke-width: 1.5;
	}
	.legend {
		display: flex;
		gap: 16px;
		font-size: 12px;
		color: var(--text-muted, #666);
		flex-wrap: wrap;
	}
	.legend-item {
		display: flex;
		align-items: center;
		gap: 4px;
	}
	.swatch {
		display: inline-block;
		width: 12px;
		height: 3px;
		border-radius: 2px;
	}
	.swatch.load { background: #d9622b; }
	.swatch.sail { background: #2e7d32; }
	.swatch.stall { background: #d32f2f; }
</style>
