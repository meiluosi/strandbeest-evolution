<script lang="ts">
import { call, runJob } from "./api";
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

let ensemble = $state(true);
let revolutions = $state(1.5);
let busy = $state("");
let error = $state("");
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
	}
}

const loadHistory = () =>
	guard("读取历史", async () => {
		history = await call("/runs");
	});

const simulate = () =>
	guard("仿真中（单次约十几秒，含范围约半分钟）", async () => {
		current = null;
		current = await runJob("/runs", {
			design: currentDesign(),
			ensemble,
			overrides: { run: { revolutions } },
		});
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

const colors = ["#e5733f", "#3f8fe5"];
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
</script>

<section>
	<h2>仿真（MuJoCo）</h2>
	<p>当前设计：{store.name}。每次运行把完整配置、代码版本和结果存在后端，可复现。</p>
	<div class="row">
		<label>转数 <input type="number" min="0.5" max="6" step="0.5" bind:value={revolutions} /></label>
		<label><input type="checkbox" bind:checked={ensemble} /> 同时跑 4 种摩擦建模，给出范围</label>
		<button disabled={!!busy} onclick={simulate}>开始仿真</button>
		<button disabled={!!busy} onclick={loadHistory}>刷新历史</button>
		{#if busy}<span>{busy}…</span>{/if}
	</div>
	{#if error}<p class="err">出错：{error}</p>{/if}

	{#if current}
		{#if current.ensemble}
			{@const r = current.ensemble.ranges}
			<table>
				<thead><tr><th>量</th><th>范围（有效的运行）</th></tr></thead>
				<tbody>
					<tr><td>每转步幅 (m)</td><td>{fmt(r, "stride_per_rev")}</td></tr>
					<tr><td>平均速度 (m/s)</td><td>{fmt(r, "mean_speed")}</td></tr>
					<tr><td>平均扭矩 (N·m)</td><td>{fmt(r, "mean_torque", 4)}</td></tr>
					<tr><td>峰值扭矩 (N·m)</td><td>{fmt(r, "peak_torque", 4)}</td></tr>
				</tbody>
			</table>
			<p class="note">{current.ensemble.note}</p>
			<details>
				<summary>各摩擦建模的结果（{current.ensemble.variants.filter((v) => v.valid).length}/{current.ensemble.variants.length} 有效）</summary>
				<table>
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
			<p>单次：每转步幅 {current.metrics.stride_per_rev?.toFixed(3)} m · 平均速度 {current.metrics.mean_speed?.toFixed(3)} m/s · 平均扭矩 {current.metrics.mean_torque?.toFixed(4)} N·m · 峰值 {current.metrics.peak_torque?.toFixed(4)} N·m{#if current.stalled}（<b>卡住了</b>）{/if}</p>
		{/if}
		<p class="note">运行编号 {current.id}</p>
	{/if}

	<h3>历史与对比</h3>
	{#if history.length === 0}<p class="note">还没有记录；先开始一次仿真或点“刷新历史”。</p>{:else}
		<table>
			<thead><tr><th>对比</th><th>编号</th><th>设计</th><th>步幅 (m)</th><th>平均扭矩 (范围)</th><th>时间</th></tr></thead>
			<tbody>
				{#each history as r}
					<tr>
						<td><input type="checkbox" checked={chosen.includes(r.id)} onchange={() => toggle(r.id)} /></td>
						<td>{r.id}</td><td>{r.design_name}</td>
						<td>{r.metrics.stride_per_rev?.toFixed(3)}</td>
						<td>{r.ranges ? fmt(r.ranges, "mean_torque", 4) : r.metrics.mean_torque?.toFixed(4)}</td>
						<td>{r.created?.slice(0, 19).replace("T", " ")}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
	{#if overlay.length}
		<p class="note">曲柄扭矩随曲柄转角（横轴 0 – {bounds.xmax.toFixed(1)} rad，纵轴 {bounds.lo.toFixed(4)} – {bounds.hi.toFixed(4)} N·m），最多选两个运行叠加：
			{#each overlay as o, i}<span style="color:{colors[i]}"> ■ {o.id}</span>{/each}</p>
		<svg viewBox="0 0 300 100" class="chart">
			{#each overlay as o, i}<polyline points={poly(o.s, bounds.lo, bounds.hi, bounds.xmax)} fill="none" stroke={colors[i]} stroke-width="1.5" />{/each}
		</svg>
	{/if}
	<small>接触、摩擦、关节间隙都是假设值，尚未用实测校准；扭矩的绝对水平依赖摩擦建模，所以报告范围。</small>
</section>

<style>
	.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; margin: 8px 0; font-size: 14px; }
	input[type="number"] { width: 70px; }
	table { border-collapse: collapse; font-size: 13px; margin: 6px 0; }
	td, th { border: 1px solid #8884; padding: 3px 8px; text-align: left; }
	tr.warn td { background: #e5c13f33; }
	.chart { width: 100%; max-width: 520px; height: 120px; border: 1px solid #8884; border-radius: 8px; }
	.note { opacity: 0.75; margin: 4px 0; font-size: 13px; }
	.err { color: #c0392b; }
	small { opacity: 0.7; }
</style>
