<script lang="ts">
import {
	crankPivot,
	gaitMetrics,
	type LinkageSpec,
	linkSegments,
	trace,
} from "strandbeest-core";
import { t } from "./i18n/index.svelte";

/** A change of one length, by handle (see lengthHandles); the viewer proposes them when a point is dragged. */
export interface LengthEdit {
	key: string;
	value: number;
}

let {
	spec,
	metrics = $bindable(null),
	onedit,
}: {
	spec: LinkageSpec;
	metrics?: { strokeLength: number; lift: number; duty: number } | null;
	/** called while a point is dragged (final = false) and once when it is released (final = true); null = cancelled */
	onedit?: (edits: LengthEdit[] | null, final: boolean) => void;
} = $props();

let canvas: HTMLCanvasElement;
let box: HTMLDivElement;
let theta = $state(0);
let playing = $state(true);
let speed = $state(1);
let size = $state({ w: 600, h: 380 });
let dragging = $state<string | null>(null);
// screen position of every drawn point and the model -> screen transform, kept by draw() for hit-testing and dragging
let screenPts: Record<string, { x: number; y: number }> = {};
let tf = { s: 1, ox: 0, oy: 0 };
let frozen: typeof tf | null = null;
let dragPose: Record<string, { x: number; y: number }> = {};

const pivot = $derived(crankPivot(spec));
const links = $derived(linkSegments(spec));
const path = $derived(trace(spec, 180));
$effect(() => {
	metrics = path.assembled ? gaitMetrics(path.foot) : null;
});

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

	if (!path.assembled) {
		ctx.fillStyle = muted;
		ctx.font = "14px system-ui";
		ctx.fillText(t("viewer.cannotClose"), 16, 28);
		return;
	}
	// fit every joint over the whole cycle into the canvas
	const pts = [pivot, ...path.poses.flatMap((p) => Object.values(p))];
	const xs = pts.map((p) => p.x);
	const ys = pts.map((p) => p.y);
	const x0 = Math.min(...xs);
	const x1 = Math.max(...xs);
	const y0 = Math.min(...ys);
	const y1 = Math.max(...ys);
	const pad = 34;
	const fitS = Math.min((w - 2 * pad) / (x1 - x0), (h - 2 * pad) / (y1 - y0));
	const fit = {
		s: fitS,
		ox: (w - fitS * (x1 - x0)) / 2 - fitS * x0,
		oy: (h - fitS * (y1 - y0)) / 2 + fitS * y1,
	};
	// while a point is dragged the picture must not rescale under the pointer, or the drag chases its own tail
	tf = dragging && frozen ? frozen : fit;
	const { s, ox, oy } = tf;
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
		P: pivot,
	};
	const color = { crank: accent, link: ink } as const;
	ctx.lineWidth = 3;
	ctx.lineCap = "round";
	for (const { a, b, kind } of links) {
		const pa = P[a];
		const pb = P[b];
		if (!pa || !pb) continue;
		ctx.strokeStyle = color[kind];
		ctx.beginPath();
		ctx.moveTo(X(pa), Y(pa));
		ctx.lineTo(X(pb), Y(pb));
		ctx.stroke();
	}
	ctx.font = "600 11px system-ui";
	screenPts = Object.fromEntries(
		Object.entries(P).map(([id, p]) => [id, { x: X(p), y: Y(p) }]),
	);
	for (const [id, p] of Object.entries(P)) {
		const fixed = id === "G" || id === "P";
		ctx.fillStyle = id === spec.foot ? accent : fixed ? muted : ink;
		ctx.beginPath();
		ctx.arc(X(p), Y(p), id === spec.foot ? 6 : 4.5, 0, 2 * Math.PI);
		ctx.fill();
		ctx.fillStyle = muted;
		ctx.fillText(id, X(p) + 8, Y(p) - 7);
	}
}

$effect(() => {
	theta;
	path;
	size;
	dragging;
	draw();
});

const refKey = (ref: string | number, inline: string) =>
	typeof ref === "string" ? ref : inline;

/** Bar lengths that put the dragged point where the pointer is: a joint is the intersection of two circles, so its two
 * radii become its distances to the two centres; the crank tip sets the crank length; the crank pivot sets x and y. */
function editsFor(id: string, x: number, y: number): LengthEdit[] {
	const r2 = (v: number) => Math.round(v * 100) / 100;
	const edits: LengthEdit[] = [];
	const add = (key: string, value: number) => {
		const v = r2(value);
		if (v > 0 || key.startsWith("crank.") || spec.params[key] !== undefined)
			edits.push({ key, value: v });
	};
	const pivotNow = crankPivot(spec);
	if (id === "P") {
		add(refKey(spec.crank.x, "crank.x"), x);
		add(refKey(spec.crank.y, "crank.y"), y);
	} else if (id === "C") {
		add(
			refKey(spec.crank.length, "crank.length"),
			Math.hypot(x - pivotNow.x, y - pivotNow.y),
		);
		theta = Math.atan2(y - pivotNow.y, x - pivotNow.x);
	} else {
		const j = spec.joints.find((q) => q.id === id);
		if (!j) return [];
		j.radii.forEach((ref, k) => {
			const c = dragPose[j.centers[k] as string];
			if (!c) return;
			const key = refKey(ref, `joint:${j.id}.radii.${k}`);
			if (!edits.some((e) => e.key === key))
				add(key, Math.hypot(x - c.x, y - c.y));
		});
	}
	return edits;
}

function toModel(e: PointerEvent): { x: number; y: number } {
	const r = canvas.getBoundingClientRect();
	return {
		x: (e.clientX - r.left - tf.ox) / tf.s,
		y: (tf.oy - (e.clientY - r.top)) / tf.s,
	};
}

function down(e: PointerEvent) {
	if (!onedit) return;
	const r = canvas.getBoundingClientRect();
	const mx = e.clientX - r.left;
	const my = e.clientY - r.top;
	let best: [string, number] | null = null;
	for (const [id, p] of Object.entries(screenPts)) {
		if (id === "G") continue; // the hip is the origin of the frame
		const d = Math.hypot(p.x - mx, p.y - my);
		if (d < 14 && (!best || d < best[1])) best = [id, d];
	}
	if (!best) return;
	frozen = { ...tf };
	dragging = best[0];
	playing = false;
	dragPose = Object.fromEntries(
		Object.entries(screenPts).map(([id, p]) => [
			id,
			{ x: (p.x - tf.ox) / tf.s, y: (tf.oy - p.y) / tf.s },
		]),
	);
	canvas.setPointerCapture(e.pointerId);
}

function move(e: PointerEvent) {
	if (!dragging || !onedit) return;
	const m = toModel(e);
	onedit(editsFor(dragging, m.x, m.y), false);
}

function up(e: PointerEvent) {
	if (!dragging || !onedit) return;
	const m = toModel(e);
	const edits = editsFor(dragging, m.x, m.y);
	dragging = null;
	frozen = null;
	onedit(edits.length ? edits : null, true);
}

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
	<canvas bind:this={canvas} style="width:{size.w}px;height:{size.h}px;cursor:{dragging ? 'grabbing' : onedit ? 'grab' : 'default'};touch-action:none" onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={() => { dragging = null; frozen = null; onedit?.(null, true); }}></canvas>
	<div class="row center">
		<button class="btn small" onclick={() => (playing = !playing)}>{playing ? t("common.pause") : t("common.play")}</button>
		<label class="inline">{t("viewer.speed")} <input type="range" min="0.2" max="4" step="0.1" bind:value={speed} style="width:120px" /></label>
		<small>
			<span style="color:var(--accent)">{t("viewer.legend.crank")}</span> <span>{t("viewer.legend.links")}</span> {t("viewer.legend.fixed")}
		</small>
	</div>
</div>


<style>
	.viewer { width: 100%; }
	canvas { display: block; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); }
</style>