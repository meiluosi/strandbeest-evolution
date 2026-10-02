<script lang="ts">
import {
	gaitMetrics,
	JANSEN_PARAM_NAMES,
	type JansenParams,
	jansenSpec,
	trace,
} from "@strandbeest/core";

let { params = $bindable() }: { params: JansenParams } = $props();

let canvas: HTMLCanvasElement;
let theta = $state(0);
let playing = $state(true);
let speed = $state(1);

const spec = $derived(jansenSpec(params));
const path = $derived(trace(spec, 180));
const metrics = $derived(path.assembled ? gaitMetrics(path.foot) : null);

const links: [string, string][] = [
	["P", "C"],
	["G", "K"],
	["K", "C"],
	["G", "L"],
	["K", "L"],
	["G", "M"],
	["C", "M"],
	["L", "N"],
	["M", "N"],
	["M", "F"],
	["N", "F"],
];

function draw() {
	const ctx = canvas.getContext("2d");
	if (!ctx) return;
	const dpr = window.devicePixelRatio || 1;
	const w = canvas.clientWidth;
	const h = canvas.clientHeight;
	canvas.width = w * dpr;
	canvas.height = h * dpr;
	ctx.scale(dpr, dpr);
	ctx.clearRect(0, 0, w, h);
	const s = Math.min(w / 190, h / 150);
	const ox = w * 0.55;
	const oy = h * 0.18;
	const X = (p: { x: number; y: number }) => ox + p.x * s;
	const Y = (p: { x: number; y: number }) => oy - p.y * s;
	const css = getComputedStyle(canvas);
	const fg = css.color;

	if (!path.assembled) {
		ctx.fillStyle = fg;
		ctx.font = "14px sans-serif";
		ctx.fillText("该参数下连杆无法闭合（拖回去试试）", 16, 28);
		return;
	}
	// foot trail
	ctx.strokeStyle = "#e5733f";
	ctx.lineWidth = 2;
	ctx.beginPath();
	path.foot.forEach((p, i) =>
		i ? ctx.lineTo(X(p), Y(p)) : ctx.moveTo(X(p), Y(p)),
	);
	ctx.closePath();
	ctx.stroke();

	const pose = {
		...(path.poses[
			Math.floor(((theta / (2 * Math.PI)) % 1) * path.poses.length)
		] ?? path.poses[0]),
	};
	const pivot = { x: params.a, y: params.l };
	const pts: Record<string, { x: number; y: number }> = { ...pose, P: pivot };
	ctx.strokeStyle = fg;
	ctx.lineWidth = 2;
	for (const [a, b] of links) {
		const pa = pts[a];
		const pb = pts[b];
		if (!pa || !pb) continue;
		ctx.beginPath();
		ctx.moveTo(X(pa), Y(pa));
		ctx.lineTo(X(pb), Y(pb));
		ctx.stroke();
	}
	for (const [id, p] of Object.entries(pts)) {
		ctx.fillStyle =
			id === "F" ? "#e5733f" : id === "G" || id === "P" ? "#888" : fg;
		ctx.beginPath();
		ctx.arc(X(p), Y(p), id === "F" ? 5 : 3.5, 0, 2 * Math.PI);
		ctx.fill();
	}
	// ground line under the foot's lowest point
	const low = Math.min(...path.foot.map((p) => p.y));
	ctx.strokeStyle = "#8888";
	ctx.setLineDash([4, 4]);
	ctx.beginPath();
	ctx.moveTo(0, Y({ x: 0, y: low }));
	ctx.lineTo(w, Y({ x: 0, y: low }));
	ctx.stroke();
	ctx.setLineDash([]);
}

$effect(() => {
	theta;
	path;
	draw();
});

$effect(() => {
	let raf = 0;
	let last = performance.now();
	const tick = (now: number) => {
		if (playing) theta += ((now - last) / 1000) * 2 * speed;
		last = now;
		raf = requestAnimationFrame(tick);
	};
	raf = requestAnimationFrame(tick);
	return () => cancelAnimationFrame(raf);
});
</script>

<div class="viewer">
	<canvas bind:this={canvas}></canvas>
	<div class="bar">
		<button onclick={() => (playing = !playing)}>{playing ? "暂停" : "播放"}</button>
		<label>转速 <input type="range" min="0.2" max="4" step="0.1" bind:value={speed} /></label>
		{#if metrics}
			<span class="metrics">
				步幅 {metrics.strokeLength.toFixed(1)} · 抬腿 {metrics.lift.toFixed(1)} · 着地占比 {(metrics.duty * 100).toFixed(0)}%
			</span>
		{/if}
	</div>
	<div class="sliders">
		{#each JANSEN_PARAM_NAMES as name}
			<label>
				<span>{name} = {params[name].toFixed(1)}</span>
				<input type="range" min="1" max="100" step="0.1" bind:value={params[name]} />
			</label>
		{/each}
	</div>
</div>

<style>
	.viewer { display: flex; flex-direction: column; gap: 8px; }
	canvas { width: 100%; height: 360px; color: inherit; border: 1px solid #8884; border-radius: 8px; }
	.bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-size: 14px; }
	.metrics { opacity: 0.8; }
	.sliders { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 6px 14px; font-size: 13px; }
	.sliders label { display: flex; flex-direction: column; }
	.sliders input { width: 100%; }
</style>
