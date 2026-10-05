<script lang="ts">
import { call, runJob } from "./api";
import { currentDesign, store } from "./store.svelte";

type Meas = {
	id: string;
	design_name: string;
	synthetic: boolean;
	conditions: { kind: string };
};
type Cmp = {
	angle_deg: number[];
	measured: (number | null)[];
	simulated: (number | null)[];
	stride_measured: number | null;
	stride_simulated: number | null;
	distance: number | null;
};
type Profile = {
	name: string;
	parameters: Record<string, number>;
	provenance: { residual: number; method: string; synthetic?: boolean };
};

let busy = $state("");
let error = $state("");
let info = $state("");
let measurements = $state<Meas[]>([]);
let runs = $state<{ id: string; design_name: string }[]>([]);
let mId = $state("");
let runId = $state("");
let cmp = $state<Cmp | null>(null);
let profile = $state<Profile | null>(null);
let calParams = $state({ contact_stiffness: true, friction: false });

// import form
let newId = $state("bench-1");
let kind = $state("motor_no_wind");
let omega = $state(2.0);
let wind = $state(0);
let synthetic = $state(false);
let channels = $state<Record<string, number[]> | null>(null);
let fileName = $state("");
// ---- raw rig data ----
type Quality = {
	sample_rate_hz: number;
	duration_s: number;
	revolutions: number;
	speed_mean_rad_s: number;
	speed_cv: number;
	dropouts: number;
	time_offset_s: number | null;
	warnings: string[];
};
let rawText = $state("");
let rawName = $state("");
let trackText = $state("");
let cal = $state({
	counts_per_motor_rev: 48,
	gear_ratio: 100,
	direction: 1,
	torque_method: "current",
	kt_nm_per_a: 0.5,
	idle_current_ma: 0,
	calibrated: false,
});
let surface = $state("");
let converted = $state<{ doc: any; q: Quality } | null>(null);

async function readText(
	e: Event,
): Promise<{ name: string; text: string } | null> {
	const f = (e.target as HTMLInputElement).files?.[0];
	return f ? { name: f.name, text: await f.text() } : null;
}
const pickRaw = async (e: Event) => {
	const r = await readText(e);
	if (r) {
		rawText = r.text;
		rawName = r.name;
		converted = null;
	}
};
const pickTrack = async (e: Event) => {
	const r = await readText(e);
	if (r) trackText = r.text;
};
const pickCal = async (e: Event) => {
	const r = await readText(e);
	if (r) cal = { ...cal, ...JSON.parse(r.text) };
};
const convertRaw = () =>
	guard("转换中", async () => {
		const doc = await call("/rig/convert", {
			raw_csv: rawText,
			raw_name: rawName,
			calibration: cal,
			id: newId,
			design_name: store.name,
			kind,
			omega,
			wind: kind === "fan" ? wind : undefined,
			surface,
			track_csv: trackText || undefined,
		});
		converted = { doc, q: doc.quality };
	});
const saveConverted = () =>
	guard("保存", async () => {
		if (!converted) return;
		await call("/measurements", converted.doc);
		measurements = await call("/measurements");
		mId = converted.doc.id;
		info = `已保存测量 ${converted.doc.id}（来自测试台）`;
	});
const timeSeries = $derived.by(() => {
	if (!converted) return null;
	const ch = converted.doc.channels;
	const tq: number[] | undefined = ch.torque;
	if (!tq) return null;
	const lo = Math.min(...tq);
	const hi = Math.max(...tq);
	const t: number[] = ch.t;
	const stride = Math.max(1, Math.floor(tq.length / 400));
	const pts = tq
		.filter((_, i) => i % stride === 0)
		.map(
			(y, i) =>
				`${((t[i * stride] as number) / (t.at(-1) as number)) * 300},${95 - ((y - lo) / (hi - lo || 1)) * 85}`,
		);
	return { pts: pts.join(" "), lo, hi };
});

async function guard(label: string, fn: () => Promise<void>) {
	busy = label;
	error = "";
	info = "";
	try {
		await fn();
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	} finally {
		busy = "";
	}
}

const refresh = () =>
	guard("读取", async () => {
		measurements = await call("/measurements");
		runs = await call("/runs");
	});

function parseCsv(text: string): Record<string, number[]> {
	const lines = text.trim().split(/\r?\n/);
	const head = (lines[0] ?? "").split(",").map((h) => h.trim());
	const out: Record<string, number[]> = Object.fromEntries(
		head.map((h) => [h, []]),
	);
	for (const line of lines.slice(1)) {
		line.split(",").forEach((v, i) => {
			const n = Number(v);
			if (!Number.isFinite(n)) throw new Error(`CSV 里有非数字值：${v}`);
			(out[head[i] as string] as number[]).push(n);
		});
	}
	return out;
}

async function pick(e: Event) {
	const f = (e.target as HTMLInputElement).files?.[0];
	if (!f) return;
	await guard("解析", async () => {
		const text = await f.text();
		fileName = f.name;
		if (f.name.endsWith(".json")) {
			const doc = JSON.parse(text);
			channels = doc.channels ?? doc;
			newId = doc.id ?? newId;
		} else channels = parseCsv(text);
		if (!channels?.t)
			throw new Error(
				"需要 t（秒）列；psi（弧度）、torque（N·m）、x（米）可选，但对照需要 psi 和 torque",
			);
		info = `读入 ${Object.keys(channels).join(", ")}，${channels.t.length} 行`;
	});
}

const save = () =>
	guard("保存", async () => {
		if (!channels) throw new Error("先选一个 CSV 或 JSON 文件");
		await call("/measurements", {
			schema_version: 1,
			id: newId,
			design_name: store.name,
			synthetic,
			conditions: {
				kind,
				omega_rad_s: omega,
				...(kind === "fan" ? { wind_m_s: wind } : {}),
			},
			channels,
		});
		measurements = await call("/measurements");
		mId = newId;
		info = `已保存测量 ${newId}`;
	});

const compare = () =>
	guard("对照中", async () => {
		cmp = await call("/compare", { measurement: mId, run_id: runId });
	});

const calibrate = () =>
	guard("校准中（数分钟，每次评估跑一次仿真）", async () => {
		const names = Object.entries(calParams)
			.filter(([, on]) => on)
			.map(([n]) => n);
		profile = await runJob("/calibrations", {
			design: currentDesign(),
			measurement: mId,
			params: names,
			max_evals: 20,
		});
	});

const chart = $derived.by(() => {
	if (!cmp) return null;
	const all = [...cmp.measured, ...cmp.simulated].filter(
		(v): v is number => v !== null,
	);
	const lo = Math.min(...all);
	const hi = Math.max(...all);
	const line = (a: (number | null)[]) =>
		a
			.map((y, i) =>
				y === null
					? null
					: `${((cmp?.angle_deg[i] as number) / 360) * 300},${95 - ((y - lo) / (hi - lo || 1)) * 85}`,
			)
			.filter(Boolean)
			.join(" ");
	return { m: line(cmp.measured), s: line(cmp.simulated), lo, hi };
});
</script>

<div class="stack">
	<div class="card">
		<h2>实验室：实测与仿真对照</h2>
		<p class="muted">把线下测的数据导入，和一次仿真叠在一起看，再让校准去拟合足垫刚度或摩擦。没有实测数据时，可以先用合成数据试链路（勾选“合成数据”）。</p>
		<div class="row center"><button class="btn" disabled={!!busy} onclick={refresh}>刷新测量与运行列表</button>{#if busy}<span class="muted"><span class="spin"></span>{busy}…</span>{/if}</div>
		{#if error}<p class="notice error">出错：{error}</p>{/if}
		{#if info}<p class="notice info">{info}</p>{/if}
	</div>

	<div class="card">
		<h3>0. 从测试台导入原始数据</h3>
		<p class="muted">测试台固件打印的 CSV（<code>t_ms,enc,current_mA,…</code>）加上标定常数，转成测量。不确定怎么标定，见 <code>hardware/README.md</code>。</p>
		<div class="row">
			<label class="btn inline" style="cursor:pointer">原始 CSV <input type="file" accept=".csv,.txt" onchange={pickRaw} hidden /></label>
			<label class="btn inline" style="cursor:pointer">视频追踪 CSV（可选） <input type="file" accept=".csv" onchange={pickTrack} hidden /></label>
			<label class="btn inline" style="cursor:pointer">导入标定 JSON <input type="file" accept=".json" onchange={pickCal} hidden /></label>
			<small>{rawName ? `原始：${rawName}` : "还没选原始文件"}{trackText ? " · 已选视频追踪" : ""}</small>
		</div>
		<div class="row">
			<label>每电机转计数 <input type="number" step="1" bind:value={cal.counts_per_motor_rev} /></label>
			<label>减速比 <input type="number" step="1" bind:value={cal.gear_ratio} /></label>
			<label>方向
				<select bind:value={cal.direction}><option value={1}>+1</option><option value={-1}>-1</option></select>
			</label>
			<label>扭矩常数 (N·m/A) <input type="number" step="0.01" bind:value={cal.kt_nm_per_a} /></label>
			<label>空载电流 (mA) <input type="number" step="1" bind:value={cal.idle_current_ma} /></label>
			<label>表面 <input type="text" bind:value={surface} size="10" placeholder="glass" /></label>
			<label class="inline"><input type="checkbox" bind:checked={cal.calibrated} /> 这些常数我已核对过</label>
		</div>
		<div class="row center">
			<small>下面“导入测量”里的编号、类型、转速、风速也用于这次转换。</small>
			<button class="btn primary" disabled={!!busy || !rawText} onclick={convertRaw}>转换并检查质量</button>
			<button class="btn" disabled={!!busy || !converted} onclick={saveConverted}>保存为测量</button>
		</div>
		{#if converted}
			<div class="cards">
				<div class="stat"><b>{converted.q.sample_rate_hz} Hz</b><span>采样率</span></div>
				<div class="stat"><b>{converted.q.revolutions}</b><span>曲柄转数</span></div>
				<div class="stat"><b>{converted.q.speed_mean_rad_s} rad/s</b><span>平均转速（波动 {(converted.q.speed_cv * 100).toFixed(1)}%）</span></div>
				<div class="stat"><b>{converted.q.dropouts}</b><span>丢包</span></div>
				{#if converted.q.time_offset_s !== null}<div class="stat"><b>{converted.q.time_offset_s} s</b><span>视频对齐偏移</span></div>{/if}
			</div>
			{#if converted.q.warnings.length}
				<div class="notice"><b>读一遍再相信这份数据：</b><ul style="margin:4px 0 0 18px; padding:0">{#each converted.q.warnings as w}<li>{w}</li>{/each}</ul></div>
			{:else}
				<p class="notice info">质量检查没有发现问题。</p>
			{/if}
			{#if timeSeries}
				<p class="muted">曲柄扭矩随时间（纵轴 {timeSeries.lo.toFixed(4)} – {timeSeries.hi.toFixed(4)} N·m）</p>
				<svg viewBox="0 0 300 100" class="chart"><polyline points={timeSeries.pts} fill="none" stroke="var(--blue)" stroke-width="1.2" /></svg>
			{/if}
		{/if}
	</div>

	<div class="card">
		<h3>1. 导入测量</h3>
		<div class="row">
			<label class="btn inline" style="cursor:pointer">选择 CSV / JSON <input type="file" accept=".csv,.json" onchange={pick} hidden /></label>
			<label>编号 <input type="text" bind:value={newId} size="12" /></label>
			<label>类型
				<select bind:value={kind}><option value="motor_no_wind">电机驱动无风</option><option value="fan">风扇</option></select>
			</label>
			<label>曲柄转速 (rad/s) <input type="number" step="0.1" bind:value={omega} /></label>
			{#if kind === "fan"}<label>风速 (m/s) <input type="number" step="0.5" min="0" bind:value={wind} /></label>{/if}
			<label class="inline"><input type="checkbox" bind:checked={synthetic} /> 合成数据</label>
			<button class="btn primary" disabled={!!busy || !channels} onclick={save}>保存测量</button>
		</div>
		<small>CSV 第一行是列名：<code>t,psi,torque,x</code>（t 秒、psi 曲柄转角 rad、torque 曲柄扭矩 N·m、x 机体前进位置 m）。{fileName ? `已选 ${fileName}` : ""}</small>
	</div>

	<div class="card">
		<h3>2. 对照</h3>
		<div class="row center">
			<label>测量
				<select bind:value={mId}>
					<option value="">选择…</option>
					{#each measurements as m}<option value={m.id}>{m.id}{m.synthetic ? "（合成）" : ""}</option>{/each}
				</select>
			</label>
			<label>仿真运行
				<select bind:value={runId}>
					<option value="">选择…</option>
					{#each runs as r}<option value={r.id}>{r.id} · {r.design_name}</option>{/each}
				</select>
			</label>
			<button class="btn primary" disabled={!!busy || !mId || !runId} onclick={compare}>对照</button>
		</div>
		{#if cmp && chart}
			<div class="cards">
				<div class="stat"><b>{cmp.distance === null ? "–" : cmp.distance.toFixed(3)}</b><span>失配度（0 = 一致）</span></div>
				{#if cmp.stride_measured !== null && cmp.stride_simulated !== null}
					<div class="stat"><b>{cmp.stride_measured.toFixed(3)} / {cmp.stride_simulated.toFixed(3)}</b><span>步幅 实测 / 仿真 (m)</span></div>
				{/if}
			</div>
			<p class="muted">扭矩随曲柄转角（0–360°，纵轴 {chart.lo.toFixed(4)} – {chart.hi.toFixed(4)} N·m）：<span style="color:var(--blue)"> ■ 实测</span> <span style="color:var(--accent)"> ■ 仿真</span></p>
			<svg viewBox="0 0 300 100" class="chart"><polyline points={chart.m} fill="none" stroke="var(--blue)" stroke-width="1.5" /><polyline points={chart.s} fill="none" stroke="var(--accent)" stroke-width="1.5" /></svg>
			<small>失配度 = 扭矩均方根差 ÷ 实测平均幅值，再加步幅相对误差。</small>
		{/if}
	</div>

	<div class="card">
		<h3>3. 校准</h3>
		<div class="row center">
			<label class="inline"><input type="checkbox" bind:checked={calParams.contact_stiffness} /> 足垫刚度</label>
			<label class="inline"><input type="checkbox" bind:checked={calParams.friction} /> 摩擦系数</label>
			<button class="btn primary" disabled={!!busy || !mId} onclick={calibrate}>用这份测量校准（当前设计）</button>
		</div>
		{#if profile}
			<table class="tbl">
				<thead><tr><th colspan="2">校准结果 {profile.name}</th></tr></thead>
				<tbody>
					{#each Object.entries(profile.parameters) as [k, v]}<tr><td>{k}</td><td>{v.toPrecision(4)}</td></tr>{/each}
					<tr><td>残差</td><td>{profile.provenance.residual.toFixed(3)}</td></tr>
					<tr><td>方法</td><td>{profile.provenance.method}</td></tr>
				</tbody>
			</table>
			{#if profile.provenance.synthetic}<p class="notice">这份结果来自合成数据，只说明链路能跑通，没有物理含义。</p>{/if}
		{/if}
		<p class="notice info">校准目前只在合成数据上验证过；真实数据的模型误差会比噪声大，拟合出的值未必有物理意义。</p>
	</div>
</div>

<style>
	.chart { width: 100%; max-width: 560px; height: 130px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); }
</style>
