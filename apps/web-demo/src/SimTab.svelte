<script lang="ts">
import { call, type Job, runJob } from "./api";
import { currentDesign, store } from "./store.svelte";

type Metrics = Record<string, number | null>;
type Variant = {
	name: string;
	valid: boolean;
	reason?: string;
	metrics: Metrics;
};
type Run = {
	id: string;
	design_name: string;
	created?: string;
	stalled: boolean;
	metrics: Metrics;
	ensemble?: {
		variants: Variant[];
		ranges: Record<string, [number, number]>;
		note: string;
	};
	ranges?: Record<string, [number, number]> | null;
};
type Series = { t: number[]; psi: number[]; torque: number[] };
type Row = {
	point: Record<string, number>;
	run_id: string | null;
	metrics: Metrics;
	valid: boolean;
	error?: string;
};

let ensemble = $state(true);
let revolutions = $state(1.5);
let busy = $state("");
let error = $state("");
let job = $state<Job | null>(null);
let current = $state<Run | null>(null);
let history = $state<Run[]>([]);
let chosen = $state<string[]>([]);
let overlay = $state<{ id: string; s: Series }[]>([]);

async function guard(label: string, fn: () => Promise<void>) {
	busy = label;
	error = "";
	try {
		await fn();
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	} finally {
		busy = "";
		job = null;
	}
}

const loadHistory = () =>
	guard("读取历史", async () => {
		history = await call("/runs");
	});

const simulate = () =>
	guard("仿真中", async () => {
		current = null;
		current = await runJob(
			"/runs",
			{
				design: currentDesign(),
				ensemble,
				overrides: { run: { revolutions } },
			},
			(j) => (job = j),
		);
		history = await call("/runs");
	});

async function toggle(id: string) {
	chosen = chosen.includes(id)
		? chosen.filter((c) => c !== id)
		: [...chosen.slice(-1), id];
	overlay = await Promise.all(
		chosen.map(async (c) => ({
			id: c,
			s: (await call(`/runs/${c}/series`)) as Series,
		})),
	);
}

// ---- sweep ----
const AXES: Record<
	string,
	{ label: string; paths: string[]; unit: string; values: string }
> = {
	stiffness: {
		label: "足垫刚度",
		paths: ["scenario.solver.contact_stiffness"],
		unit: "N/m",
		values: "1000, 3000, 10000, 30000",
	},
	friction: {
		label: "摩擦系数",
		paths: ["scenario.walker.foot_friction", "scenario.terrain.friction"],
		unit: "",
		values: "0.5, 0.8, 1.2, 2.0",
	},
	legs: {
		label: "腿数",
		paths: ["design.walker.legs"],
		unit: "",
		values: "4, 6, 8, 12",
	},
	omega: {
		label: "曲柄转速",
		paths: ["scenario.drive.omega"],
		unit: "rad/s",
		values: "1, 2, 3, 4",
	},
};
let axisKey = $state("stiffness");
let valuesText = $state(AXES.stiffness?.values ?? "");
let metricKey = $state("stride_per_rev");
let sweepRows = $state<Row[] | null>(null);
let sweepJob = $state<string | null>(null);
let sweepUnit = $state("");

function pickAxis() {
	valuesText = AXES[axisKey]?.values ?? "";
}

const sweep = () =>
	guard("扫描中", async () => {
		const ax = AXES[axisKey];
		if (!ax) return;
		const values = valuesText
			.split(",")
			.map((v) => Number(v.trim()))
			.filter((v) => Number.isFinite(v));
		if (!values.length) throw new Error("请填入用逗号分隔的数值");
		sweepRows = null;
		sweepUnit = `${ax.label}${ax.unit ? ` (${ax.unit})` : ""}`;
		const axes = [{ path: ax.paths[0], also: ax.paths.slice(1), values }];
		const res = await runJob(
			"/sweeps",
			{
				design: currentDesign(),
				axes,
				overrides: { run: { revolutions: 1.2, settle: 0.5 } },
			},
			(j) => {
				job = j;
				sweepJob = j.id;
			},
		);
		sweepRows = res.rows as Row[];
		history = await call("/runs");
	});

const cancel = async () => {
	if (job) await call(`/jobs/${job.id}/cancel`, {});
};

const colors = ["#d9622b", "#2f6fd1"];
function poly(s: Series, lo: number, hi: number, xmax: number): string {
	return s.torque
		.map(
			(y, i) =>
				`${((s.psi[i] as number) / xmax) * 300},${95 - ((y - lo) / (hi - lo || 1)) * 85}`,
		)
		.join(" ");
}
const bounds = $derived.by(() => {
	const all = overlay.flatMap((o) => o.s.torque);
	const xs = overlay.flatMap((o) => o.s.psi);
	return { lo: Math.min(...all), hi: Math.max(...all), xmax: Math.max(...xs) };
});
const fmt = (
	r: Record<string, [number, number]> | null | undefined,
	k: string,
	d = 3,
) => (r?.[k] ? `${r[k][0].toFixed(d)} – ${r[k][1].toFixed(d)}` : "–");
const pointValue = (r: Row) => Object.values(r.point)[0] as number;
const sweepPlot = $derived.by(() => {
	if (!sweepRows) return null;
	const pts = sweepRows
		.filter((r) => r.valid && typeof r.metrics[metricKey] === "number")
		.map((r) => ({ x: pointValue(r), y: r.metrics[metricKey] as number }))
		.sort((a, b) => a.x - b.x);
	if (pts.length < 2) return null;
	const xs = pts.map((p) => p.x);
	const ys = pts.map((p) => p.y);
	const [xl, xh, yl, yh] = [
		Math.min(...xs),
		Math.max(...xs),
		Math.min(...ys),
		Math.max(...ys),
	];
	const log = xl > 0 && xh / xl > 20;
	const fx = (x: number) =>
		log
			? (Math.log(x) - Math.log(xl)) / (Math.log(xh) - Math.log(xl))
			: (x - xl) / (xh - xl || 1);
	return {
		pts: pts
			.map(
				(p) =>
					`${10 + fx(p.x) * 280},${90 - ((p.y - yl) / (yh - yl || 1)) * 75}`,
			)
			.join(" "),
		yl,
		yh,
		xl,
		xh,
		log,
	};
});
</script>

<div class="stack">
	<div class="card">
		<h2>仿真（MuJoCo）</h2>
		<p class="muted">当前设计：<b>{store.name}</b>。每次运行把完整配置、代码版本和结果存在后端，可复现。</p>
		<div class="row center">
			<label>转数 <input type="number" min="0.5" max="6" step="0.5" bind:value={revolutions} /></label>
			<label class="inline"><input type="checkbox" bind:checked={ensemble} /> 同时跑 4 种摩擦建模，给出范围</label>
			<button class="btn primary" disabled={!!busy} onclick={simulate}>开始仿真</button>
			{#if busy}
				<span class="muted"><span class="spin"></span>{busy}…{#if job?.progress.total} {job.progress.done}/{job.progress.total}{/if}</span>
				{#if job && job.id}<button class="btn small" onclick={cancel}>取消</button>{/if}
			{/if}
		</div>
		{#if error}<p class="notice error">出错：{error}</p>{/if}

		{#if current}
			{#if current.ensemble}
				{@const r = current.ensemble.ranges}
				<div class="cards" style="margin-top:10px">
					<div class="stat"><b>{fmt(r, "stride_per_rev")}</b><span>每转步幅 (m)</span></div>
					<div class="stat"><b>{fmt(r, "mean_speed")}</b><span>平均速度 (m/s)</span></div>
					<div class="stat"><b>{fmt(r, "mean_torque", 4)}</b><span>平均扭矩 (N·m)</span></div>
					<div class="stat"><b>{fmt(r, "peak_torque", 4)}</b><span>峰值扭矩 (N·m)</span></div>
				</div>
				<p class="notice">{current.ensemble.note}</p>
				<details>
					<summary>各摩擦建模的结果（{current.ensemble.variants.filter((v) => v.valid).length}/{current.ensemble.variants.length} 有效）</summary>
					<table class="tbl">
						<thead><tr><th>设置</th><th>有效</th><th>步幅</th><th>平均扭矩</th><th>环约束偏差 (mm)</th></tr></thead>
						<tbody>
							{#each current.ensemble.variants as v}
								<tr class={v.valid ? "" : "warn"}>
									<td>{v.name}</td><td>{v.valid ? "是" : `否（${v.reason}）`}</td>
									<td>{v.metrics.stride_per_rev?.toFixed(3)}</td><td>{v.metrics.mean_torque?.toFixed(4)}</td>
									<td>{((v.metrics.max_loop_violation ?? 0) * 1000).toFixed(2)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</details>
			{:else}
				<div class="cards" style="margin-top:10px">
					<div class="stat"><b>{current.metrics.stride_per_rev?.toFixed(3)}</b><span>每转步幅 (m)</span></div>
					<div class="stat"><b>{current.metrics.mean_speed?.toFixed(3)}</b><span>平均速度 (m/s)</span></div>
					<div class="stat"><b>{current.metrics.mean_torque?.toFixed(4)}</b><span>平均扭矩 (N·m)</span></div>
					<div class="stat"><b>{current.metrics.peak_torque?.toFixed(4)}</b><span>峰值扭矩 (N·m)</span></div>
				</div>
				{#if current.stalled}<p class="notice error">这次运行卡住了。</p>{/if}
			{/if}
			<small>运行编号 {current.id}</small>
		{/if}
		<p class="notice info">接触、摩擦、关节间隙都是假设值，尚未用实测校准；扭矩的绝对水平依赖摩擦建模，所以报告范围。</p>
	</div>

	<div class="card">
		<h2>参数扫描</h2>
		<p class="muted">沿一个参数跑一串仿真，看结果怎么变；每个点都是一次完整、可复现的运行。最多 60 个点。</p>
		<div class="row center">
			<label>参数
				<select bind:value={axisKey} onchange={pickAxis}>{#each Object.entries(AXES) as [k, a]}<option value={k}>{a.label}</option>{/each}</select>
			</label>
			<label>取值（逗号分隔） <input type="text" bind:value={valuesText} size="26" /></label>
			<button class="btn primary" disabled={!!busy} onclick={sweep}>开始扫描</button>
			{#if busy === "扫描中" && job?.progress.total}
				<div style="width:140px"><div class="bar"><div style="width:{(job.progress.done / job.progress.total) * 100}%"></div></div><small>{job.progress.done}/{job.progress.total}</small></div>
			{/if}
		</div>
		{#if sweepRows}
			<div class="row center">
				<label>看哪个量
					<select bind:value={metricKey}>
						<option value="stride_per_rev">每转步幅 (m)</option>
						<option value="mean_torque">平均扭矩 (N·m)</option>
						<option value="peak_torque">峰值扭矩 (N·m)</option>
						<option value="torque_ptp">扭矩峰峰值 (N·m)</option>
						<option value="max_loop_violation">环约束偏差 (m)</option>
					</select>
				</label>
			</div>
			<table class="tbl">
				<thead><tr><th>{sweepUnit}</th><th>有效</th><th>每转步幅</th><th>平均扭矩</th><th>峰值扭矩</th><th>环约束偏差 (mm)</th></tr></thead>
				<tbody>
					{#each sweepRows as r}
						<tr class={r.valid ? "" : "warn"}>
							<td>{pointValue(r)}</td><td>{r.valid ? "是" : (r.error ?? "否（环约束张开或卡住）")}</td>
							<td>{r.metrics.stride_per_rev?.toFixed(3) ?? "–"}</td><td>{r.metrics.mean_torque?.toFixed(4) ?? "–"}</td><td>{r.metrics.peak_torque?.toFixed(4) ?? "–"}</td>
							<td>{r.metrics.max_loop_violation !== undefined && r.metrics.max_loop_violation !== null ? (r.metrics.max_loop_violation * 1000).toFixed(2) : "–"}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			{#if sweepPlot}
				<svg viewBox="0 0 300 100" class="chart"><polyline points={sweepPlot.pts} fill="none" stroke="var(--accent)" stroke-width="2" /></svg>
				<small>横轴 {sweepPlot.xl} – {sweepPlot.xh}{sweepPlot.log ? "（对数）" : ""}，纵轴 {sweepPlot.yl.toPrecision(3)} – {sweepPlot.yh.toPrecision(3)}（只画有效的点）</small>
			{/if}
		{/if}
	</div>

	<div class="card">
		<div class="row center" style="justify-content: space-between; margin: 0 0 6px">
			<h2 style="margin: 0">历史与对比</h2>
			<button class="btn small" disabled={!!busy} onclick={loadHistory}>刷新</button>
		</div>
		{#if history.length === 0}<p class="muted">还没有记录；先开始一次仿真或点“刷新”。</p>{:else}
			<table class="tbl">
				<thead><tr><th>对比</th><th>编号</th><th>设计</th><th>步幅 (m)</th><th>平均扭矩</th><th>时间</th></tr></thead>
				<tbody>
					{#each history as r}
						<tr>
							<td><input type="checkbox" checked={chosen.includes(r.id)} onchange={() => toggle(r.id)} /></td>
							<td>{r.id}</td><td>{r.design_name}</td><td>{r.metrics.stride_per_rev?.toFixed(3)}</td>
							<td>{r.ranges ? fmt(r.ranges, "mean_torque", 4) : r.metrics.mean_torque?.toFixed(4)}</td>
							<td class="muted">{r.created?.slice(0, 19).replace("T", " ")}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
		{#if overlay.length}
			<p class="muted">曲柄扭矩随曲柄转角（最多选两个叠加）：{#each overlay as o, i}<span style="color:{colors[i]}"> ■ {o.id}</span>{/each}
				· 纵轴 {bounds.lo.toFixed(4)} – {bounds.hi.toFixed(4)} N·m，横轴 0 – {bounds.xmax.toFixed(1)} rad</p>
			<svg viewBox="0 0 300 100" class="chart">
				{#each overlay as o, i}<polyline points={poly(o.s, bounds.lo, bounds.hi, bounds.xmax)} fill="none" stroke={colors[i]} stroke-width="1.5" />{/each}
			</svg>
		{/if}
	</div>
</div>

<style>
	.chart { width: 100%; max-width: 560px; height: 130px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); margin-top: 6px; display: block; }
</style>
