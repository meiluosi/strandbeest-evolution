<script lang="ts">
import {
	gaitMetrics,
	type JansenParams,
	jansenSpec,
	trace,
} from "strandbeest-core";

let {
	params,
	metrics = $bindable(null),
}: {
	params: JansenParams;
	metrics?: { strokeLength: number; lift: number; duty: number } | null;
} = $props();

let canvas: HTMLCanvasElement;
let box: HTMLDivElement;
let theta = $state(0);
let playing = $state(true);
let speed = $state(1);
let size = $state({ w: 600, h: 380 });

const spec = $derived(jansenSpec(params));
const path = $derived(trace(spec, 180));
$effect(() => {
	metrics = path.assembled ? gaitMetrics(path.foot) : null;
});

const links: [string, string, string][] = [
	["P", "C", "crank"],
	["G", "K", "upper"],
	["K", "C", "upper"],
	["G", "L", "upper"],
	["K", "L", "upper"],
	["G", "M", "lower"],
	["C", "M", "lower"],
	["L", "N", "lower"],
	["M", "N", "lower"],
	["M", "F", "lower"],
	["N", "F", "lower"],
];

function cssVar(name: string): string {
	return getComputedStyle(canvas).getPropertyValue(name).trim();
}

function draw() {
	const ctx = canvas.getContext("2d");
	if (!ctx) return;
	const dpr = window.devicePixelRatio || 1;
	const { w, h } = size;
	canvas.width = w * dpr;
	canvas.height = h * dpr;
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);
	const ink = cssVar("--ink");
	const muted = cssVar("--muted");
	const accent = cssVar("--accent");
	const blue = cssVar("--blue");

	if (!path.assembled) {
		ctx.fillStyle = muted;
		ctx.font = "14px system-ui";
		ctx.fillText("该参数下连杆无法闭合：把滑块拖回去试试", 16, 28);
		return;
	}
	// fit every joint over the whole cycle into the canvas
	const pts = [
		{ x: params.a, y: params.l },
		...path.poses.flatMap((p) => Object.values(p)),
	];
	const xs = pts.map((p) => p.x);
	const ys = pts.map((p) => p.y);
	const x0 = Math.min(...xs);
	const x1 = Math.max(...xs);
	const y0 = Math.min(...ys);
	const y1 = Math.max(...ys);
	const pad = 34;
	const s = Math.min((w - 2 * pad) / (x1 - x0), (h - 2 * pad) / (y1 - y0));
	const ox = (w - s * (x1 - x0)) / 2 - s * x0;
	const oy = (h - s * (y1 - y0)) / 2 + s * y1;
	const X = (p: { x: number; y: number }) => ox + p.x * s;
	const Y = (p: { x: number; y: number }) => oy - p.y * s;

	// ground under the lowest foot position
	const low = Math.min(...path.foot.map((p) => p.y));
	ctx.strokeStyle = muted;
	ctx.globalAlpha = 0.5;
	ctx.setLineDash([5, 5]);
	ctx.beginPath();
	ctx.moveTo(10, Y({ x: 0, y: low }));
	ctx.lineTo(w - 10, Y({ x: 0, y: low }));
	ctx.stroke();
	ctx.setLineDash([]);
	ctx.globalAlpha = 1;

	// foot trail
	ctx.strokeStyle = accent;
	ctx.lineWidth = 2.5;
	ctx.beginPath();
	path.foot.forEach((p, i) =>
		i ? ctx.lineTo(X(p), Y(p)) : ctx.moveTo(X(p), Y(p)),
	);
	ctx.closePath();
	ctx.stroke();

	const idx = Math.floor(
		((((theta / (2 * Math.PI)) % 1) + 1) % 1) * path.poses.length,
	);
	const pose = path.poses[idx] ?? path.poses[0];
	const P: Record<string, { x: number; y: number }> = {
		...pose,
		P: { x: params.a, y: params.l },
	};
	const color = { crank: accent, upper: blue, lower: ink } as const;
	ctx.lineWidth = 3;
	ctx.lineCap = "round";
	for (const [a, b, kind] of links) {
		const pa = P[a];
		const pb = P[b];
		if (!pa || !pb) continue;
		ctx.strokeStyle = color[kind as keyof typeof color];
		ctx.beginPath();
		ctx.moveTo(X(pa), Y(pa));
		ctx.lineTo(X(pb), Y(pb));
		ctx.stroke();
	}
	ctx.font = "600 11px system-ui";
	for (const [id, p] of Object.entries(P)) {
		const fixed = id === "G" || id === "P";
		ctx.fillStyle = id === "F" ? accent : fixed ? muted : ink;
		ctx.beginPath();
		ctx.arc(X(p), Y(p), id === "F" ? 6 : 4.5, 0, 2 * Math.PI);
		ctx.fill();
		ctx.fillStyle = muted;
		ctx.fillText(id, X(p) + 8, Y(p) - 7);
	}
}

$effect(() => {
	theta;
	path;
	size;
	draw();
});

$effect(() => {
	const ro = new ResizeObserver(() => {
		size = {
			w: Math.max(280, box.clientWidth),
			h: Math.max(260, Math.min(420, box.clientWidth * 0.62)),
		};
	});
	ro.observe(box);
	return () => ro.disconnect();
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

<div bind:this={box} class="viewer">
	<canvas bind:this={canvas} style="width:{size.w}px;height:{size.h}px"></canvas>
	<div class="row center">
		<button class="btn small" onclick={() => (playing = !playing)}>{playing ? "暂停" : "播放"}</button>
		<label class="inline">转速 <input type="range" min="0.2" max="4" step="0.1" bind:value={speed} style="width:120px" /></label>
		<small>
			<span style="color:var(--accent)">■ 曲柄/脚轨迹</span> <span style="color:var(--blue)">■ 上部三角</span> <span>■ 下肢</span> · G、P 是固定铰
		</small>
	</div>
</div>

<style>
	.viewer { width: 100%; }
	canvas { display: block; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); }
</style>
