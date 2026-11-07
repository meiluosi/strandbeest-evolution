<script lang="ts">
import EvidenceBadge from "./EvidenceBadge.svelte";
import { t } from "./i18n/index.svelte";
import {
	CALIBRATED_MPP,
	computeFootTrajectoryKinematic,
	computeFootTrajectoryMeasured,
	computeFootTrajectorySimulated,
	computePhaseCurves,
	computeStrideMetrics,
	computeVelocitySeries,
	FULLSCALE_UNIT_M,
	getBinnenhofBenchmark,
	MEASURED_STRIDE_M,
	type Point2D,
	parseMeasurementData,
	SCALE_UNCERTAINTY_MPP,
	SCALE_UNCERTAINTY_PCT,
	SIMULATED_STRIDE_M,
	THEORETICAL_STRIDE_M,
} from "./video-twin";

type ViewMode = "trajectory" | "displacement" | "velocity";

let benchmark = $state(getBinnenhofBenchmark());
let viewMode = $state<ViewMode>("trajectory");
let activeName = $state("binnenhof-strandbeest-2016");
let customMetrics = $state(getBinnenhofBenchmark().nominal);
let customActive = $state(false);
let errorMessage = $state("");
let infoMessage = $state("");
let fileInput = $state<HTMLInputElement | null>(null);

// Hover tooltip state
let hoverX = $state<number | null>(null);
let hoverY = $state<number | null>(null);
let hoverText = $state("");

function loadBenchmark() {
	benchmark = getBinnenhofBenchmark();
	activeName = "binnenhof-strandbeest-2016";
	customMetrics = benchmark.nominal;
	customActive = false;
	errorMessage = "";
	infoMessage = "";
}

async function handleFileUpload(e: Event) {
	const target = e.target as HTMLInputElement;
	const file = target.files?.[0];
	if (!file) return;

	try {
		errorMessage = "";
		infoMessage = "";
		const text = await file.text();
		const parsed = parseMeasurementData(text, file.name);

		activeName = parsed.name;
		customMetrics = {
			...benchmark.nominal,
			measured_stride_m: parsed.stride_m,
			measured_sigma_m: parsed.metrics.uncertainty_m,
			ci95_lo_m: parsed.metrics.ci95_lo_m,
			ci95_hi_m: parsed.metrics.ci95_hi_m,
			sigma_lo_m: parsed.metrics.sigma_lo_m,
			sigma_hi_m: parsed.metrics.sigma_hi_m,
			rel_diff_sim_pct: parsed.metrics.rel_diff_sim_pct,
			rel_diff_kin_pct: parsed.metrics.rel_diff_kin_pct,
			within_envelope: parsed.metrics.within_envelope,
			duration_s: parsed.duration_s,
			dx_m: parsed.dx_m,
			v_mean_m_s: parsed.v_mean_m_s,
			revolutions: parsed.revolutions,
		};
		customActive = true;
		infoMessage = t("videoTwin.customLoaded", { name: parsed.name });
	} catch (err) {
		errorMessage = t("videoTwin.errParse", {
			error: err instanceof Error ? err.message : String(err),
		});
	} finally {
		if (target) target.value = "";
	}
}

// Coordinate conversions for SVG Plot 1: Foot Trajectory (X-Z)
// World bounds: x in [-0.75, 0.75] m, z in [-1.80, -1.20] m
// SVG bounds: 600 x 280 (plot area: left 60, right 570, top 30, bottom 240)
const SVG_W = 600;
const SVG_H = 280;
const PAD_L = 60;
const PAD_R = 30;
const PAD_T = 30;
const PAD_B = 40;
const PLOT_W = SVG_W - PAD_L - PAD_R;
const PLOT_H = SVG_H - PAD_T - PAD_B;

function mapTrajectory(pt: Point2D): [number, number] {
	const px = PAD_L + ((pt.x - -0.75) / 1.5) * PLOT_W;
	const py = PAD_T + PLOT_H - ((pt.z - -1.8) / 0.6) * PLOT_H;
	return [px, py];
}

function polylinePoints(pts: Point2D[]): string {
	return pts
		.map(mapTrajectory)
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" ");
}

const trajTheoretical = $derived(
	polylinePoints(benchmark.foot_trajectories.theoretical),
);
const trajSimulated = $derived(
	polylinePoints(benchmark.foot_trajectories.simulated),
);
const trajMeasured = $derived(
	polylinePoints(benchmark.foot_trajectories.measured),
);

// Uncertainty band polygon for foot curve
const trajBandPolygon = $derived.by(() => {
	const upper =
		benchmark.foot_trajectories.measured_ci95_upper.map(mapTrajectory);
	const lower = benchmark.foot_trajectories.measured_ci95_lower
		.map(mapTrajectory)
		.reverse();
	const all = [...upper, ...lower];
	return all.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
});

// Ground contact line level at z = -1.72 m
const groundLineY = $derived(PAD_T + PLOT_H - ((-1.72 - -1.8) / 0.6) * PLOT_H);

// Coordinate conversions for SVG Plot 2: Displacement over Crank Phase (Δx(θ))
// Crank angle theta in [0, 2*pi], dx in [0, 3.2] m
function mapPhase(theta: number, dx: number): [number, number] {
	const px = PAD_L + (theta / (2.0 * Math.PI)) * PLOT_W;
	const py = PAD_T + PLOT_H - (dx / 3.2) * PLOT_H;
	return [px, py];
}

const phaseTheoretical = $derived(
	benchmark.phase_curves.theoretical
		.map((p) => mapPhase(p.theta, p.dx))
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" "),
);

const phaseSimulated = $derived(
	benchmark.phase_curves.simulated
		.map((p) => mapPhase(p.theta, p.dx))
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" "),
);

const phaseMeasured = $derived(
	benchmark.phase_curves.measured
		.map((p) => mapPhase(p.theta, p.dx))
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" "),
);

const phaseCi95Polygon = $derived.by(() => {
	const pts = benchmark.phase_curves.measured;
	const upper = pts.map((p) => mapPhase(p.theta, p.dx_ci95_hi));
	const lower = pts.map((p) => mapPhase(p.theta, p.dx_ci95_lo)).reverse();
	return [...upper, ...lower]
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" ");
});

const phaseSigmaPolygon = $derived.by(() => {
	const pts = benchmark.phase_curves.measured;
	const upper = pts.map((p) => mapPhase(p.theta, p.dx_sigma_hi));
	const lower = pts.map((p) => mapPhase(p.theta, p.dx_sigma_lo)).reverse();
	return [...upper, ...lower]
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" ");
});

// Coordinate conversions for SVG Plot 3: Velocity Profile (v(t))
// Time t in [0, 10.0] s, v in [0.08, 0.16] m/s
function mapVelocity(tSec: number, v: number): [number, number] {
	const px = PAD_L + (tSec / 10.0) * PLOT_W;
	const py = PAD_T + PLOT_H - ((v - 0.08) / 0.08) * PLOT_H;
	return [px, py];
}

const velMeasured = $derived(
	benchmark.velocity_series
		.map((p) => mapVelocity(p.t, p.v_meas))
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" "),
);
const velSimulated = $derived(
	benchmark.velocity_series
		.map((p) => mapVelocity(p.t, p.v_sim))
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" "),
);
const velKinematic = $derived(
	benchmark.velocity_series
		.map((p) => mapVelocity(p.t, p.v_kin))
		.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
		.join(" "),
);

function onSvgMouseMove(e: MouseEvent) {
	const rect = (e.currentTarget as SVGElement).getBoundingClientRect();
	const relX = e.clientX - rect.left;
	const relY = e.clientY - rect.top;

	if (
		relX >= PAD_L &&
		relX <= PAD_L + PLOT_W &&
		relY >= PAD_T &&
		relY <= PAD_T + PLOT_H
	) {
		hoverX = relX;
		hoverY = relY;

		if (viewMode === "trajectory") {
			const wx = -0.75 + ((relX - PAD_L) / PLOT_W) * 1.5;
			const wz = -1.8 + ((PAD_T + PLOT_H - relY) / PLOT_H) * 0.6;
			hoverText = `X: ${wx.toFixed(3)} m, Z: ${wz.toFixed(3)} m`;
		} else if (viewMode === "displacement") {
			const theta = ((relX - PAD_L) / PLOT_W) * (2.0 * Math.PI);
			const dx = ((PAD_T + PLOT_H - relY) / PLOT_H) * 3.2;
			hoverText = `θ: ${theta.toFixed(2)} rad, Δx: ${dx.toFixed(3)} m`;
		} else {
			const tSec = ((relX - PAD_L) / PLOT_W) * 10.0;
			const v = 0.08 + ((PAD_T + PLOT_H - relY) / PLOT_H) * 0.08;
			hoverText = `t: ${tSec.toFixed(2)} s, v: ${v.toFixed(3)} m/s`;
		}
	} else {
		hoverX = null;
		hoverY = null;
		hoverText = "";
	}
}

function onSvgMouseLeave() {
	hoverX = null;
	hoverY = null;
	hoverText = "";
}
</script>

<div class="video-twin-panel card">
	<div class="header-row">
		<div>
			<div class="title-with-badge">
				<h3>{t("videoTwin.title")}</h3>
				<EvidenceBadge
					evidence={{
						level: "E0",
						basis: ["Binnenhof CC BY 3.0 (Chassis x(t))", "Cadence assumed (0.045 Hz)"],
						downgraded: true,
						downgrade_reason: "Crank cadence is an unverified assumption; optical flow only tracked chassis position without tracked crank/feet",
					}}
				/>
				<span class="badge evidence-tag">{t("videoTwin.badge")}</span>
			</div>
			<p class="muted">{t("videoTwin.subtitle")}</p>
		</div>
		<div class="actions-row">
			<button class="btn" class:primary={!customActive} onclick={loadBenchmark}>
				{t("videoTwin.loadBenchmark")}
			</button>
			<label class="btn inline file-btn">
				{t("videoTwin.uploadCustom")}
				<input
					type="file"
					accept=".json,.csv"
					onchange={handleFileUpload}
					bind:this={fileInput}
					hidden
				/>
			</label>
		</div>
	</div>

	{#if errorMessage}
		<p class="notice error">{errorMessage}</p>
	{/if}
	{#if infoMessage}
		<p class="notice info">{infoMessage}</p>
	{/if}

	<!-- Stats Summary Grid -->
	<div class="cards stats-grid">
		<div class="stat">
			<b>{customMetrics.measured_stride_m.toFixed(3)} m/rev</b>
			<span>{t("videoTwin.colStride")} (±{customMetrics.measured_sigma_m.toFixed(3)})</span>
		</div>
		<div class="stat">
			<b class={customMetrics.rel_diff_sim_pct <= 0 ? "dev-down" : "dev-up"}>
				{customMetrics.rel_diff_sim_pct > 0 ? "+" : ""}{customMetrics.rel_diff_sim_pct.toFixed(2)}%
			</b>
			<span>vs {t("videoTwin.modelSimulation")} (2.921)</span>
		</div>
		<div class="stat">
			<b class={customMetrics.rel_diff_kin_pct <= 0 ? "dev-down" : "dev-up"}>
				{customMetrics.rel_diff_kin_pct > 0 ? "+" : ""}{customMetrics.rel_diff_kin_pct.toFixed(2)}%
			</b>
			<span>vs {t("videoTwin.modelTheoretical")} (2.875)</span>
		</div>
		<div class="stat">
			<b>{customMetrics.v_mean_m_s.toFixed(3)} m/s</b>
			<span>{t("videoTwin.statMeanVelocity")}</span>
		</div>
	</div>

	<!-- Interactive Chart Section -->
	<div class="plot-container">
		<div class="plot-toolbar">
			<span class="muted font-mono">{t("videoTwin.viewMode")}:</span>
			<div class="btn-group">
				<button
					class="btn small"
					class:active={viewMode === "trajectory"}
					onclick={() => (viewMode = "trajectory")}
				>
					{t("videoTwin.plotTrajectory")}
				</button>
				<button
					class="btn small"
					class:active={viewMode === "displacement"}
					onclick={() => (viewMode = "displacement")}
				>
					{t("videoTwin.plotDisplacement")}
				</button>
				<button
					class="btn small"
					class:active={viewMode === "velocity"}
					onclick={() => (viewMode = "velocity")}
				>
					{t("videoTwin.plotVelocity")}
				</button>
			</div>
		</div>

		<!-- SVG Canvas -->
		<svg
			viewBox="0 0 {SVG_W} {SVG_H}"
			class="plot-svg"
			role="region"
			aria-label="Visual graph plot"
			onmousemove={onSvgMouseMove}
			onmouseleave={onSvgMouseLeave}
		>
			<!-- Grid lines & Background axes -->
			<g class="grid">
				<line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + PLOT_H} stroke="var(--line)" />
				<line x1={PAD_L} y1={PAD_T + PLOT_H} x2={PAD_L + PLOT_W} y2={PAD_T + PLOT_H} stroke="var(--line)" />

				{#if viewMode === "trajectory"}
					<!-- Vertical center line x=0 -->
					<line
						x1={PAD_L + PLOT_W / 2}
						y1={PAD_T}
						x2={PAD_L + PLOT_W / 2}
						y2={PAD_T + PLOT_H}
						stroke="var(--line)"
						stroke-dasharray="2,3"
					/>
					<!-- Ground level line z=-1.72 m -->
					<line
						x1={PAD_L}
						y1={groundLineY}
						x2={PAD_L + PLOT_W}
						y2={groundLineY}
						stroke="rgba(150, 150, 150, 0.4)"
						stroke-width="1.5"
						stroke-dasharray="4,3"
					/>
					<text x={PAD_L + 6} y={groundLineY - 4} class="axis-hint font-mono">z = -1.72 m</text>
				{:else if viewMode === "displacement"}
					<!-- Phase markers pi and 2pi -->
					<line
						x1={PAD_L + PLOT_W / 2}
						y1={PAD_T}
						x2={PAD_L + PLOT_W / 2}
						y2={PAD_T + PLOT_H}
						stroke="var(--line)"
						stroke-dasharray="2,3"
					/>
					<text x={PAD_L + PLOT_W / 2 - 10} y={PAD_T + PLOT_H + 16} class="axis-hint">π</text>
					<text x={PAD_L + PLOT_W - 12} y={PAD_T + PLOT_H + 16} class="axis-hint">2π</text>
				{/if}
			</g>

			<!-- Plot View: Trajectory (X-Z) -->
			{#if viewMode === "trajectory"}
				<!-- 95% Confidence Band -->
				<polygon points={trajBandPolygon} fill="rgba(245, 158, 11, 0.18)" />

				<!-- Theoretical Kinematics (Blue dashed) -->
				<polyline
					points={trajTheoretical}
					fill="none"
					stroke="#2563eb"
					stroke-width="2"
					stroke-dasharray="5,3"
				/>

				<!-- MuJoCo Forward Sim (Green solid) -->
				<polyline
					points={trajSimulated}
					fill="none"
					stroke="#10b981"
					stroke-width="2"
				/>

				<!-- Empirical Binnenhof Video (Amber solid with markers) -->
				<polyline
					points={trajMeasured}
					fill="none"
					stroke="#f59e0b"
					stroke-width="2.5"
				/>
			{:else if viewMode === "displacement"}
				<!-- 95% CI Band -->
				<polygon points={phaseCi95Polygon} fill="rgba(245, 158, 11, 0.15)" />
				<!-- 1-sigma Band -->
				<polygon points={phaseSigmaPolygon} fill="rgba(245, 158, 11, 0.28)" />

				<!-- Theoretical Kinematics Curve (Blue dashed) -->
				<polyline
					points={phaseTheoretical}
					fill="none"
					stroke="#2563eb"
					stroke-width="2"
					stroke-dasharray="5,3"
				/>

				<!-- MuJoCo Simulation Curve (Green solid) -->
				<polyline
					points={phaseSimulated}
					fill="none"
					stroke="#10b981"
					stroke-width="2"
				/>

				<!-- Measured Video Curve (Amber solid) -->
				<polyline
					points={phaseMeasured}
					fill="none"
					stroke="#f59e0b"
					stroke-width="2.5"
				/>
			{:else}
				<!-- Velocity Series (v(t)) -->
				<polyline
					points={velKinematic}
					fill="none"
					stroke="#2563eb"
					stroke-width="1.8"
					stroke-dasharray="5,3"
				/>
				<polyline
					points={velSimulated}
					fill="none"
					stroke="#10b981"
					stroke-width="1.8"
				/>
				<polyline
					points={velMeasured}
					fill="none"
					stroke="#f59e0b"
					stroke-width="2.2"
				/>
			{/if}

			<!-- Interactive Hover Pointer -->
			{#if hoverX !== null && hoverY !== null}
				<line
					x1={hoverX}
					y1={PAD_T}
					x2={hoverX}
					y2={PAD_T + PLOT_H}
					stroke="rgba(100, 100, 100, 0.5)"
					stroke-width="1"
					stroke-dasharray="2,2"
				/>
				<line
					x1={PAD_L}
					y1={hoverY}
					x2={PAD_L + PLOT_W}
					y2={hoverY}
					stroke="rgba(100, 100, 100, 0.5)"
					stroke-width="1"
					stroke-dasharray="2,2"
				/>
				<circle cx={hoverX} cy={hoverY} r="4" fill="#f59e0b" stroke="#fff" stroke-width="1.5" />
			{/if}

			<!-- Axis Labels -->
			<text x={PAD_L - 8} y={PAD_T + 10} text-anchor="end" class="axis-label font-mono">
				{viewMode === "trajectory" ? t("videoTwin.axisZ") : viewMode === "displacement" ? t("videoTwin.axisDeltaX") : "v (m/s)"}
			</text>
			<text x={PAD_L + PLOT_W} y={PAD_T + PLOT_H + 28} text-anchor="end" class="axis-label font-mono">
				{viewMode === "trajectory" ? t("videoTwin.axisX") : viewMode === "displacement" ? t("videoTwin.axisTheta") : "t (s)"}
			</text>
		</svg>

		<!-- Tooltip Bar & Legend -->
		<div class="legend-bar">
			<div class="legend-item">
				<span class="legend-swatch kin"></span>
				<small>{t("videoTwin.legendTheoretical")} (2.875)</small>
			</div>
			<div class="legend-item">
				<span class="legend-swatch sim"></span>
				<small>{t("videoTwin.legendSimulation")} (2.921)</small>
			</div>
			<div class="legend-item">
				<span class="legend-swatch meas"></span>
				<small>{t("videoTwin.legendMeasured")} ({customMetrics.measured_stride_m.toFixed(3)})</small>
			</div>
			<div class="legend-item">
				<span class="legend-swatch band"></span>
				<small>{t("videoTwin.legendCi95")}</small>
			</div>
			<div class="legend-item">
				<span class="legend-swatch sigma"></span>
				<small>{t("videoTwin.legendSigma")}</small>
			</div>
			{#if hoverText}
				<div class="hover-readout font-mono">
					{hoverText}
				</div>
			{/if}
		</div>
	</div>

	<!-- 3-Way Comparison Table -->
	<div class="table-container">
		<h4>{t("videoTwin.tableTitle")}</h4>
		<table class="tbl comparison-table">
			<thead>
				<tr>
					<th>{t("videoTwin.colModel")}</th>
					<th>{t("videoTwin.colStride")}</th>
					<th>{t("videoTwin.colDeviation")}</th>
					<th>{t("videoTwin.colEnvelope")}</th>
					<th>{t("videoTwin.colEvidence")}</th>
				</tr>
			</thead>
			<tbody>
				<!-- Empirical Row -->
				<tr class="highlight-row">
					<td>
						<b>{t("videoTwin.modelMeasured")}</b>
						<small class="muted"> ({activeName})</small>
					</td>
					<td>
						<b>{customMetrics.measured_stride_m.toFixed(3)}</b>
						<small class="muted"> ±{customMetrics.measured_sigma_m.toFixed(3)}</small>
					</td>
					<td>
						<span class="badge baseline-badge">{t("videoTwin.baseline")}</span>
					</td>
					<td>
						<span class="badge ok">
							{customMetrics.within_envelope ? t("videoTwin.withinEnvelope") : t("videoTwin.outsideEnvelope")}
						</span>
						<small class="muted"> [2.505, 3.097]</small>
					</td>
					<td>
						<span class="evidence-chip e0">E0 Assumption</span>
					</td>
				</tr>

				<!-- Theoretical Row -->
				<tr>
					<td>
						<span>{t("videoTwin.modelTheoretical")}</span>
						<small class="muted"> (Jansen holy numbers)</small>
					</td>
					<td>{THEORETICAL_STRIDE_M.toFixed(3)}</td>
					<td>
						<span class={customMetrics.rel_diff_kin_pct <= 0 ? "dev-down" : "dev-up"}>
							{customMetrics.rel_diff_kin_pct > 0 ? "+" : ""}{customMetrics.rel_diff_kin_pct.toFixed(2)}%
						</span>
					</td>
					<td>
						<span class="badge ok">{t("videoTwin.withinEnvelope")}</span>
						<small class="muted"> (Δ = 0.074 m)</small>
					</td>
					<td>
						<span class="evidence-chip e1">E1 Model</span>
					</td>
				</tr>

				<!-- MuJoCo Sim Row -->
				<tr>
					<td>
						<span>{t("videoTwin.modelSimulation")}</span>
						<small class="muted"> (50 kg full-scale contact-v3)</small>
					</td>
					<td>{SIMULATED_STRIDE_M.toFixed(3)}</td>
					<td>
						<span class={customMetrics.rel_diff_sim_pct <= 0 ? "dev-down" : "dev-up"}>
							{customMetrics.rel_diff_sim_pct > 0 ? "+" : ""}{customMetrics.rel_diff_sim_pct.toFixed(2)}%
						</span>
					</td>
					<td>
						<span class="badge ok">{t("videoTwin.withinEnvelope")}</span>
						<small class="muted"> (Δ = 0.120 m)</small>
					</td>
					<td>
						<span class="evidence-chip e1">E1 Simulation</span>
					</td>
				</tr>
			</tbody>
		</table>
	</div>

	<!-- Literature Baseline Callout -->
	<div class="literature-callout">
		<div class="lit-header">
			<span class="lit-icon">📚</span>
			<b>{t("videoTwin.literatureTitle")}</b>
		</div>
		<p class="lit-body">
			{t("videoTwin.literatureText")}
		</p>
	</div>

	<!-- Video Provenance & Traceability -->
	<div class="provenance-card">
		<div class="prov-header">
			<b>{t("videoTwin.provenanceTitle")}</b>
			<span class="badge cc-badge">{benchmark.provenance.license}</span>
		</div>
		<div class="prov-grid">
			<div class="prov-item">
				<span class="prov-label">{t("videoTwin.provenanceSource")}:</span>
				<span class="prov-value">{benchmark.provenance.video_title} ({benchmark.provenance.author})</span>
			</div>
			<div class="prov-item">
				<span class="prov-label">{t("videoTwin.provenanceLicense")}:</span>
				<span class="prov-value">{benchmark.provenance.license}</span>
			</div>
			<div class="prov-item">
				<span class="prov-label">{t("videoTwin.provenanceSha")}:</span>
				<code class="prov-code">{benchmark.provenance.sha256}</code>
			</div>
			<div class="prov-item">
				<span class="prov-label">{t("videoTwin.provenanceScale")}:</span>
				<span class="prov-value">{t("videoTwin.provenanceScaleDesc")}</span>
			</div>
			<div class="prov-item">
				<span class="prov-label">{t("videoTwin.statCrankCadence")}:</span>
				<span class="prov-value">f = {benchmark.nominal.f_crank_hz} Hz (T = {benchmark.nominal.crank_period_s} s, ω = {benchmark.nominal.omega_rad_s} rad/s)</span>
			</div>
			<div class="prov-item">
				<span class="prov-label">{t("videoTwin.statRevolutions")}:</span>
				<span class="prov-value">{benchmark.nominal.revolutions} rev ({benchmark.nominal.duration_s} s, Δx = {benchmark.nominal.dx_m} m)</span>
			</div>
		</div>
	</div>
</div>

<style>
	.video-twin-panel {
		display: flex;
		flex-direction: column;
		gap: 16px;
		margin-bottom: 20px;
	}

	.header-row {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
	}

	.title-with-badge {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.title-with-badge h3 {
		margin: 0;
	}

	.evidence-tag {
		background: #2563eb22;
		color: #2563eb;
		font-weight: 600;
	}

	.actions-row {
		display: flex;
		gap: 8px;
		align-items: center;
	}

	.file-btn {
		cursor: pointer;
	}

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
		gap: 12px;
	}

	.dev-down {
		color: #2563eb;
	}

	.dev-up {
		color: #d97706;
	}

	.plot-container {
		display: flex;
		flex-direction: column;
		gap: 8px;
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 12px;
		background: var(--bg);
	}

	.plot-toolbar {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}

	.btn-group {
		display: flex;
		border-radius: 6px;
		overflow: hidden;
		border: 1px solid var(--line);
	}

	.btn-group .btn {
		border-radius: 0;
		border: none;
		border-right: 1px solid var(--line);
		background: var(--bg);
	}

	.btn-group .btn:last-child {
		border-right: none;
	}

	.btn-group .btn.active {
		background: var(--line);
		font-weight: 600;
	}

	.plot-svg {
		width: 100%;
		height: 260px;
		background: var(--bg);
		user-select: none;
	}

	.axis-label {
		font-size: 11px;
		fill: var(--muted);
	}

	.axis-hint {
		font-size: 10px;
		fill: var(--muted);
	}

	.legend-bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 14px;
		padding-top: 4px;
	}

	.legend-item {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.legend-swatch {
		width: 14px;
		height: 3px;
		border-radius: 2px;
	}

	.legend-swatch.kin {
		background: #2563eb;
	}

	.legend-swatch.sim {
		background: #10b981;
	}

	.legend-swatch.meas {
		background: #f59e0b;
		height: 4px;
	}

	.legend-swatch.band {
		background: rgba(245, 158, 11, 0.3);
		height: 8px;
	}

	.legend-swatch.sigma {
		background: rgba(245, 158, 11, 0.5);
		height: 8px;
	}

	.hover-readout {
		margin-left: auto;
		font-size: 11px;
		color: var(--accent);
		background: var(--bg-alt, rgba(120, 120, 120, 0.1));
		padding: 2px 6px;
		border-radius: 4px;
	}

	.table-container {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.table-container h4 {
		margin: 0;
	}

	.comparison-table {
		width: 100%;
		border-collapse: collapse;
	}

	.highlight-row {
		background: rgba(245, 158, 11, 0.06);
	}

	.baseline-badge {
		background: #f59e0b22;
		color: #d97706;
		font-weight: 600;
	}

	.evidence-chip {
		font-size: 10px;
		padding: 2px 6px;
		border-radius: 4px;
		font-family: monospace;
		font-weight: 600;
	}

	.evidence-chip.e0 {
		background: #f59e0b22;
		color: #d97706;
		border: 1px solid #f59e0b55;
	}

	.evidence-chip.e1 {
		background: #3b82f622;
		color: #2563eb;
		border: 1px solid #3b82f655;
	}

	.literature-callout {
		background: rgba(59, 130, 246, 0.06);
		border-left: 3px solid #2563eb;
		padding: 10px 14px;
		border-radius: 0 6px 6px 0;
	}

	.lit-header {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 4px;
		font-size: 13px;
	}

	.lit-body {
		margin: 0;
		font-size: 12px;
		color: var(--muted);
		line-height: 1.5;
	}

	.provenance-card {
		border: 1px dashed var(--line);
		border-radius: 6px;
		padding: 10px 14px;
		background: rgba(120, 120, 120, 0.03);
	}

	.prov-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
	}

	.cc-badge {
		background: #10b98122;
		color: #059669;
		font-weight: 600;
	}

	.prov-grid {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 11px;
	}

	.prov-item {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.prov-label {
		color: var(--muted);
		min-width: 130px;
	}

	.prov-value {
		color: var(--fg);
	}

	.prov-code {
		font-size: 10px;
		background: var(--line);
		padding: 1px 4px;
		border-radius: 3px;
		word-break: break-all;
	}
</style>
