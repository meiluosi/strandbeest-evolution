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

<section>
	<h2>实验室：实测与仿真对照</h2>
	<p class="note">把线下测的数据导入、和一次仿真叠在一起看，再让校准去拟合足垫刚度/摩擦。没有实测数据时，可以先用合成数据试链路（勾选“合成数据”）。</p>
	<div class="row"><button disabled={!!busy} onclick={refresh}>刷新测量与运行列表</button>{#if busy}<span>{busy}…</span>{/if}</div>
	{#if error}<p class="err">出错：{error}</p>{/if}
	{#if info}<p class="note">{info}</p>{/if}

	<h3>导入测量</h3>
	<div class="row">
		<label class="file">CSV / JSON <input type="file" accept=".csv,.json" onchange={pick} /></label>
		<label>编号 <input type="text" bind:value={newId} size="12" /></label>
		<label>类型
			<select bind:value={kind}><option value="motor_no_wind">电机驱动无风</option><option value="fan">风扇</option></select>
		</label>
		<label>曲柄转速 rad/s <input type="number" step="0.1" bind:value={omega} /></label>
		{#if kind === "fan"}<label>风速 m/s <input type="number" step="0.5" min="0" bind:value={wind} /></label>{/if}
		<label><input type="checkbox" bind:checked={synthetic} /> 合成数据</label>
		<button disabled={!!busy || !channels} onclick={save}>保存测量</button>
	</div>
	<p class="note">CSV 第一行是列名：<code>t,psi,torque,x</code>（t 秒、psi 曲柄转角 rad、torque 曲柄扭矩 N·m、x 机体前进位置 m）。{fileName ? `已选 ${fileName}` : ""}</p>

	<h3>对照与校准</h3>
	<div class="row">
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
		<button disabled={!!busy || !mId || !runId} onclick={compare}>对照</button>
	</div>
	{#if cmp && chart}
		<p>失配度 {cmp.distance === null ? "–" : cmp.distance.toFixed(3)}（0 表示一致；扭矩均方根差除以实测平均幅值，加上步幅相对误差）
			{#if cmp.stride_measured !== null && cmp.stride_simulated !== null}· 步幅 实测 {cmp.stride_measured.toFixed(3)} m / 仿真 {cmp.stride_simulated.toFixed(3)} m{/if}</p>
		<p class="note">扭矩随曲柄转角（0–360°，纵轴 {chart.lo.toFixed(4)} – {chart.hi.toFixed(4)} N·m）：<span style="color:#3f8fe5"> ■ 实测</span> <span style="color:#e5733f"> ■ 仿真</span></p>
		<svg viewBox="0 0 300 100" class="chart"><polyline points={chart.m} fill="none" stroke="#3f8fe5" stroke-width="1.5" /><polyline points={chart.s} fill="none" stroke="#e5733f" stroke-width="1.5" /></svg>
	{/if}
	<div class="row">
		<label><input type="checkbox" bind:checked={calParams.contact_stiffness} /> 足垫刚度</label>
		<label><input type="checkbox" bind:checked={calParams.friction} /> 摩擦系数</label>
		<button disabled={!!busy || !mId} onclick={calibrate}>用这份测量校准（当前设计）</button>
	</div>
	{#if profile}
		<table>
			<thead><tr><th colspan="2">校准结果 {profile.name}</th></tr></thead>
			<tbody>
				{#each Object.entries(profile.parameters) as [k, v]}<tr><td>{k}</td><td>{v.toPrecision(4)}</td></tr>{/each}
				<tr><td>残差</td><td>{profile.provenance.residual.toFixed(3)}</td></tr>
				<tr><td>方法</td><td>{profile.provenance.method}</td></tr>
			</tbody>
		</table>
		{#if profile.provenance.synthetic}<p class="note">这份结果来自合成数据，只说明链路能跑通，没有物理含义。</p>{/if}
	{/if}
	<small>校准目前只在合成数据上验证过；真实数据的模型误差会比噪声大，拟合出的值未必有物理意义。</small>
</section>

<style>
	.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; margin: 8px 0; font-size: 14px; }
	input[type="number"] { width: 80px; }
	table { border-collapse: collapse; font-size: 13px; margin: 6px 0; }
	td, th { border: 1px solid #8884; padding: 3px 8px; text-align: left; }
	.chart { width: 100%; max-width: 520px; height: 120px; border: 1px solid #8884; border-radius: 8px; }
	.note { opacity: 0.75; margin: 4px 0; font-size: 13px; }
	.err { color: #c0392b; }
	small { opacity: 0.7; }
	.file input { font-size: 12px; }
</style>
