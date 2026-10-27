<script lang="ts">
import {
	crankPivot,
	evenPhases,
	gaitMetrics,
	type LinkageSpec,
	linkSegments,
	linkTriangles,
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
	theta = $bindable(0),
	legs = 6,
	windOmega = null,
	windSpeed = 0,
	stalledAt = null,
	onedit,
}: {
	spec: LinkageSpec;
	metrics?: { strokeLength: number; lift: number; duty: number } | null;
	theta?: number;
	legs?: number;
	/** when non-null, drive the crank at this angular speed (rad/s) instead of constant manual speed */
	windOmega?: number | null;
	/** visual wind speed (m/s) for wind streamlines when windOmega is active or > 0 */
	windSpeed?: number;
	/** if the wind cannot push past a stall angle (rad), rock gently near this angle */
	stalledAt?: number | null;
	/** called while a point is dragged (final = false) and once when it is released (final = true); null = cancelled */
	onedit?: (edits: LengthEdit[] | null, final: boolean) => void;
} = $props();

let canvas: HTMLCanvasElement;
let box: HTMLDivElement;
let playing = $state(true);
let speed = $state(1);
let showMultiLegs = $state(true);
let showTruss = $state(true);
let size = $state({ w: 600, h: 380 });
let dragging = $state<string | null>(null);
let hoveredJoint = $state<string | null>(null);
let scrollX = 0;
let gustBoost = $state(0);
// screen position of every drawn point and the model -> screen transform, kept by draw() for hit-testing and dragging
let screenPts: Record<string, { x: number; y: number }> = {};
let tf = { s: 1, ox: 0, oy: 0 };
let frozen: typeof tf | null = null;
let dragPose: Record<string, { x: number; y: number }> = {};

const pivot = $derived(crankPivot(spec));
const links = $derived(linkSegments(spec));
const triangles = $derived(linkTriangles(spec));
const path = $derived(trace(spec, 180));
$effect(() => {
	metrics = path.assembled ? gaitMetrics(path.foot) : null;
});

// Deterministic wind streamline seeds for canvas
const windParticles = Array.from({ length: 22 }, (_, i) => ({
	x: ((i * 73) % 100) / 100,
	y: 0.08 + (((i * 41) % 80) / 100) * 0.78,
	len: 18 + (i % 4) * 9,
	speedMul: 0.8 + (i % 5) * 0.12,
}));

function cssVar(name: string): string {
	return getComputedStyle(canvas).getPropertyValue(name).trim();
}

function drawLegPose(
	ctx: CanvasRenderingContext2D,
	P: Record<string, { x: number; y: number }>,
	X: (p: { x: number; y: number }) => number,
	Y: (p: { x: number; y: number }) => number,
	alpha: number,
	isPrimary: boolean,
	ink: string,
	muted: string,
	accent: string,
) {
	ctx.save();
	ctx.globalAlpha = alpha;

	// 1. Rigid triangles (ternary links) fill
	if (showTruss && triangles.length > 0) {
		ctx.fillStyle = isPrimary ? accent : muted;
		ctx.globalAlpha = alpha * (isPrimary ? 0.13 : 0.05);
		for (const [u, v, w] of triangles) {
			const pu = P[u];
			const pv = P[v];
			const pw = P[w];
			if (!pu || !pv || !pw) continue;
			ctx.beginPath();
			ctx.moveTo(X(pu), Y(pu));
			ctx.lineTo(X(pv), Y(pv));
			ctx.lineTo(X(pw), Y(pw));
			ctx.closePath();
			ctx.fill();
		}
		ctx.globalAlpha = alpha;
	}

	// 2. Bars
	const color = { crank: accent, link: ink } as const;
	ctx.lineWidth = isPrimary ? 3.2 : 1.6;
	ctx.lineCap = "round";
	for (const { a, b, kind } of links) {
		const pa = P[a];
		const pb = P[b];
		if (!pa || !pb) continue;
		ctx.strokeStyle = isPrimary ? color[kind] : muted;
		ctx.beginPath();
		ctx.moveTo(X(pa), Y(pa));
		ctx.lineTo(X(pb), Y(pb));
		ctx.stroke();
	}

	// 3. Joints
	for (const [id, p] of Object.entries(P)) {
		const fixed = id === "G" || id === "P";
		const isFoot = id === spec.foot;
		const isHovered = isPrimary && (hoveredJoint === id || dragging === id);
		if (!isPrimary && !isFoot) continue;

		if (isHovered) {
			ctx.fillStyle = accent;
			ctx.globalAlpha = 0.25;
			ctx.beginPath();
			ctx.arc(X(p), Y(p), 11, 0, 2 * Math.PI);
			ctx.fill();
			ctx.globalAlpha = alpha;
		}

		ctx.fillStyle = isFoot ? accent : fixed ? muted : ink;
		ctx.beginPath();
		ctx.arc(
			X(p),
			Y(p),
			isFoot ? (isPrimary ? 6.5 : 3.5) : fixed ? 5 : 4.2,
			0,
			2 * Math.PI,
		);
		ctx.fill();

		// Inner pin hole for mechanical look on primary leg
		if (isPrimary) {
			ctx.fillStyle = cssVar("--bg") || "#fff";
			ctx.beginPath();
			ctx.arc(X(p), Y(p), isFoot ? 2.2 : 1.7, 0, 2 * Math.PI);
			ctx.fill();
		}
	}
	ctx.restore();
}

function draw() {
	if (!canvas) return;
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
	const ok = cssVar("--ok") || "#2e8b57";

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
	const pad = 38;
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

	// Wind streamlines in background when windSpeed > 0
	const effectiveWind = windSpeed + gustBoost;
	if (effectiveWind > 0.1) {
		ctx.save();
		ctx.strokeStyle = accent;
		ctx.lineCap = "round";
		const windAlpha = Math.min(0.32, 0.06 + effectiveWind * 0.018);
		for (const wp of windParticles) {
			const px = (((wp.x * w + scrollX * wp.speedMul * 1.8) % w) + w) % w;
			const py = wp.y * h;
			const len = wp.len * (0.6 + effectiveWind * 0.08);
			ctx.globalAlpha = windAlpha * (0.5 + 0.5 * Math.sin(px * 0.02));
			ctx.lineWidth = 1.3;
			ctx.beginPath();
			ctx.moveTo(px, py);
			ctx.lineTo(px + len, py);
			ctx.stroke();
		}
		ctx.restore();
	}

	// Ground under the lowest foot position with scrolling beach ticks
	const low = Math.min(...path.foot.map((p) => p.y));
	const high = Math.max(...path.foot.map((p) => p.y));
	const stanceThreshold = low + 0.02 * (high - low);
	const groundY = Y({ x: 0, y: low });

	ctx.save();
	ctx.strokeStyle = muted;
	ctx.globalAlpha = 0.45;
	ctx.lineWidth = 1.2;
	ctx.beginPath();
	ctx.moveTo(10, groundY);
	ctx.lineTo(w - 10, groundY);
	ctx.stroke();

	// Moving ground hash ticks to convey forward body progression
	const tickSpacing = 24;
	const tickOffset = ((scrollX % tickSpacing) + tickSpacing) % tickSpacing;
	ctx.globalAlpha = 0.28;
	ctx.beginPath();
	for (let tx = 14 + tickOffset; tx < w - 14; tx += tickSpacing) {
		ctx.moveTo(tx, groundY);
		ctx.lineTo(tx - 6, groundY + 7);
	}
	ctx.stroke();
	ctx.restore();

	// Crank circle guide
	const crankR = Math.hypot(
		(path.poses[0]?.C?.x ?? pivot.x) - pivot.x,
		(path.poses[0]?.C?.y ?? pivot.y) - pivot.y,
	);
	ctx.save();
	ctx.strokeStyle = muted;
	ctx.globalAlpha = 0.22;
	ctx.setLineDash([3, 3]);
	ctx.beginPath();
	ctx.arc(X(pivot), Y(pivot), crankR * s, 0, 2 * Math.PI);
	ctx.stroke();
	ctx.restore();

	// Multi-leg ghost poses (phased legs behind the primary leg)
	const nLegs = Math.max(1, Math.min(12, Math.round(legs || 6)));
	if (showMultiLegs && nLegs > 1) {
		const phases = evenPhases(nLegs);
		for (let k = 1; k < phases.length; k++) {
			const ph = phases[k]!.phase;
			const phIdx = Math.floor(
				(((((theta + ph) / (2 * Math.PI)) % 1) + 1) % 1) * path.poses.length,
			);
			const phPose = path.poses[phIdx] ?? path.poses[0];
			if (!phPose) continue;
			drawLegPose(
				ctx,
				{ ...phPose, P: pivot },
				X,
				Y,
				0.18,
				false,
				ink,
				muted,
				accent,
			);
		}
	}

	// Foot trail: highlight stance phase (flat bottom) vs swing phase
	ctx.save();
	ctx.lineWidth = 2.5;
	for (let i = 0; i < path.foot.length; i++) {
		const p0 = path.foot[i]!;
		const p1 = path.foot[(i + 1) % path.foot.length]!;
		const inStance = p0.y <= stanceThreshold && p1.y <= stanceThreshold;
		ctx.strokeStyle = inStance ? ok : accent;
		ctx.globalAlpha = inStance ? 0.95 : 0.7;
		ctx.beginPath();
		ctx.moveTo(X(p0), Y(p0));
		ctx.lineTo(X(p1), Y(p1));
		ctx.stroke();
	}
	ctx.restore();

	// Primary leg pose
	const idx = Math.floor(
		((((theta / (2 * Math.PI)) % 1) + 1) % 1) * path.poses.length,
	);
	const pose = path.poses[idx] ?? path.poses[0];
	const P: Record<string, { x: number; y: number }> = {
		...pose,
		P: pivot,
	};
	drawLegPose(ctx, P, X, Y, 1, true, ink, muted, accent);

	// Joint labels
	ctx.font = "600 11px system-ui";
	screenPts = Object.fromEntries(
		Object.entries(P).map(([id, p]) => [id, { x: X(p), y: Y(p) }]),
	);
	for (const [id, p] of Object.entries(P)) {
		ctx.fillStyle = hoveredJoint === id || dragging === id ? accent : muted;
		ctx.fillText(id, X(p) + 8, Y(p) - 7);
	}

	// Crank angle & wind HUD badge inside canvas top-right
	const deg = Math.round(((((theta * 180) / Math.PI) % 360) + 360) % 360);
	ctx.save();
	ctx.font = "500 11.5px ui-monospace, SFMono-Regular, Menlo, monospace";
	ctx.fillStyle = muted;
	ctx.textAlign = "right";
	ctx.fillText(`θ = ${deg}°`, w - 14, 22);
	if (stalledAt !== null && windOmega === 0) {
		ctx.fillStyle = cssVar("--bad") || "#c0392b";
		ctx.fillText(t("viewer.stalledBadge"), w - 14, 38);
	}
	ctx.restore();
}

$effect(() => {
	theta;
	path;
	size;
	dragging;
	hoveredJoint;
	showMultiLegs;
	showTruss;
	legs;
	windSpeed;
	gustBoost;
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

function hitJoint(e: PointerEvent): string | null {
	const r = canvas.getBoundingClientRect();
	const mx = e.clientX - r.left;
	const my = e.clientY - r.top;
	let best: [string, number] | null = null;
	for (const [id, p] of Object.entries(screenPts)) {
		if (id === "G") continue; // the hip is the origin of the frame
		const d = Math.hypot(p.x - mx, p.y - my);
		if (d < 14 && (!best || d < best[1])) best = [id, d];
	}
	return best ? best[0] : null;
}

function down(e: PointerEvent) {
	if (!onedit) return;
	const hit = hitJoint(e);
	if (!hit) return;
	frozen = { ...tf };
	dragging = hit;
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
	if (!dragging) {
		hoveredJoint = onedit ? hitJoint(e) : null;
		return;
	}
	if (!onedit) return;
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

export function triggerGust() {
	gustBoost = 6;
	playing = true;
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
		const dt = Math.min(0.05, (now - last) / 1000);
		last = now;
		if (gustBoost > 0) {
			gustBoost = Math.max(0, gustBoost - dt * 3.2);
		}
		if (playing && !dragging) {
			if (windOmega !== null) {
				const effOmega = windOmega + (gustBoost > 0 ? gustBoost * 0.45 : 0);
				if (effOmega > 0.01) {
					// Jansen leg walks forward when crank turns in -theta direction
					theta -= dt * effOmega * speed;
					scrollX -= dt * effOmega * speed * 28;
				} else if (stalledAt !== null) {
					// Gently oscillate against the stall barrier when wind is too weak
					const target = stalledAt;
					const diff =
						((((target - theta + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) %
							(2 * Math.PI)) -
						Math.PI;
					const wobble = Math.sin(now * 0.007) * 0.06;
					theta += diff * Math.min(1, dt * 6) + wobble * dt * 4;
				}
			} else {
				theta -= dt * 2 * speed;
				scrollX -= dt * 2 * speed * 28;
			}
		}
		raf = requestAnimationFrame(tick);
	};
	raf = requestAnimationFrame(tick);
	return () => cancelAnimationFrame(raf);
});
</script>

<div bind:this={box} class="viewer">
	<canvas
		bind:this={canvas}
		style="width:{size.w}px;height:{size.h}px;cursor:{dragging ? 'grabbing' : hoveredJoint ? 'grab' : 'default'};touch-action:none"
		onpointerdown={down}
		onpointermove={move}
		onpointerup={up}
		onpointerleave={() => (hoveredJoint = null)}
		onpointercancel={() => { dragging = null; frozen = null; onedit?.(null, true); }}
	></canvas>
	<div class="row center controls-bar">
		<button class="btn small" onclick={() => (playing = !playing)}>{playing ? t("common.pause") : t("common.play")}</button>
		<label class="inline">{t("viewer.speed")} <input type="range" min="0.2" max="4" step="0.1" bind:value={speed} style="width:96px" /></label>
		<label class="inline"><input type="checkbox" bind:checked={showMultiLegs} /> {t("viewer.multiLegs")}</label>
		<label class="inline"><input type="checkbox" bind:checked={showTruss} /> {t("viewer.truss")}</label>
		<small class="legend-text">
			<span style="color:var(--accent)">{t("viewer.legend.crank")}</span> · <span style="color:var(--ok)">{t("viewer.legend.stance")}</span> · <span>{t("viewer.legend.links")}</span> {t("viewer.legend.fixed")}
		</small>
	</div>
</div>


<style>
	.viewer { width: 100%; }
	canvas { display: block; max-width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); }
	.controls-bar { gap: 8px 12px; }
	.legend-text { margin-left: auto; }
</style>