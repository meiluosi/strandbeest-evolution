<script lang="ts">
import { t } from "./i18n/index.svelte";
import type { Replay } from "./replay-types";

/** Footfall diagram (one row per leg, stance in colour) and the phase ring (stance of leg 1 against the crank angle). */
let {
	replay,
	time,
	onseek,
}: { replay: Replay; time: number; onseek: (t: number) => void } = $props();

const W = 600;
const rowH = 14;
const left = 28;
const legs = $derived(replay.info.legs);
const t0 = $derived(replay.t[0] as number);
const t1 = $derived(replay.t[replay.t.length - 1] as number);
const x = (tt: number) =>
	left + ((tt - t0) / Math.max(t1 - t0, 1e-9)) * (W - left - 6);

const stances = $derived.by(() => {
	const out: { leg: number; a: number; b: number }[] = [];
	for (let k = 0; k < legs; k++) {
		let start = -1;
		replay.contact.forEach((row, f) => {
			const down = !!row[k];
			if (down && start < 0) start = f;
			if ((!down || f === replay.contact.length - 1) && start >= 0) {
				out.push({
					leg: k,
					a: replay.t[start] as number,
					b: replay.t[down ? f : f - 1] as number,
				});
				start = -1;
			}
		});
	}
	return out;
});
const stanceFraction = $derived(
	replay.contact.length
		? replay.contact.reduce((s, r) => s + r.reduce((q, c) => q + c, 0), 0) /
				(replay.contact.length * legs)
		: 0,
);

function seek(e: MouseEvent) {
	const r = (e.currentTarget as SVGElement).getBoundingClientRect();
	const f = ((e.clientX - r.left) / r.width) * W;
	onseek(t0 + ((f - left) / (W - left - 6)) * (t1 - t0));
}

// phase ring: for each 5 degree bin of the crank angle, is leg 1 on the ground (majority of frames)?
const ring = $derived.by(() => {
	const bins = 72;
	const down = new Array(bins).fill(0);
	const seen = new Array(bins).fill(0);
	const st = replay.series.t;
	const psi = replay.series.psi;
	let j = 0;
	replay.t.forEach((tt, f) => {
		while (j < st.length - 2 && (st[j + 1] as number) < tt) j++;
		const a = psi[j] as number;
		const b = psi[Math.min(j + 1, psi.length - 1)] as number;
		const ta = st[j] as number;
		const tb = st[Math.min(j + 1, st.length - 1)] as number;
		const p = a + ((b - a) * (tt - ta)) / Math.max(tb - ta, 1e-9);
		const bin =
			((Math.floor(
				((((p % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) /
					(2 * Math.PI)) *
					bins,
			) %
				bins) +
				bins) %
			bins;
		seen[bin]++;
		if ((replay.contact[f] as number[])[0]) down[bin]++;
	});
	return down.map((d, i) => (seen[i] ? d / seen[i] > 0.5 : false));
});
const phaseNow = $derived.by(() => {
	const st = replay.series.t;
	let j = st.findIndex((v) => v >= time);
	if (j < 0) j = st.length - 1;
	return (
		(((replay.series.psi[j] as number) % (2 * Math.PI)) + 2 * Math.PI) %
		(2 * Math.PI)
	);
});
const arc = (i: number, r: number) => {
	const a0 = (i / 72) * 2 * Math.PI - Math.PI / 2;
	const a1 = ((i + 1) / 72) * 2 * Math.PI - Math.PI / 2;
	return `M ${60 + r * Math.cos(a0)} ${60 + r * Math.sin(a0)} A ${r} ${r} 0 0 1 ${60 + r * Math.cos(a1)} ${60 + r * Math.sin(a1)}`;
};
const kinematic = $derived(replay.kinematic_duty);
</script>

<div class="foot">
	<div class="diagram">
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<svg viewBox="0 0 {W} {legs * rowH + 8}" onclick={seek} role="button" tabindex="-1" aria-label={t("footfall.title")}>
			{#each Array.from({ length: legs }) as _, k}
				<text x="2" y={k * rowH + 11} class="lab">{k + 1}</text>
				<line x1={left} x2={W - 6} y1={k * rowH + rowH - 1} y2={k * rowH + rowH - 1} class="axis" />
			{/each}
			{#each stances as s}
				<rect x={x(s.a)} y={s.leg * rowH + 2} width={Math.max(1.5, x(s.b) - x(s.a))} height={rowH - 5} class="stance" />
			{/each}
			<line x1={x(time)} x2={x(time)} y1="0" y2={legs * rowH} class="cursor" />
		</svg>
		<small>{t("footfall.stats", { sim: `${(stanceFraction * 100).toFixed(0)}%` })}{#if kinematic != null} {t("footfall.kinematic", { duty: `${(kinematic * 100).toFixed(0)}%` })}{/if}</small>
	</div>
	<div class="ring">
		<svg viewBox="0 0 120 120" role="img" aria-label={t("footfall.phase")}>
			<circle cx="60" cy="60" r="44" class="base" />
			{#each ring as on, i}{#if on}<path d={arc(i, 44)} class="on" />{/if}{/each}
			<line x1="60" y1="60" x2={60 + 40 * Math.cos(phaseNow - Math.PI / 2)} y2={60 + 40 * Math.sin(phaseNow - Math.PI / 2)} class="hand" />
			<text x="60" y="64" class="mid">{Math.round((phaseNow * 180) / Math.PI)}°</text>
		</svg>
		<small>{t("footfall.phase")}</small>
	</div>
</div>

<style>
	.foot { display: grid; grid-template-columns: 1fr 130px; gap: 12px; align-items: start; }
	svg { width: 100%; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); cursor: pointer; }
	.ring svg { cursor: default; border: none; background: transparent; }
	.lab { font-size: 9px; fill: var(--muted); }
	.axis { stroke: var(--line); stroke-width: 0.5; }
	.stance { fill: #2e8b57; }
	.cursor { stroke: var(--accent); stroke-width: 1.2; }
	.base { fill: none; stroke: var(--line); stroke-width: 8; }
	.on { fill: none; stroke: #2e8b57; stroke-width: 8; }
	.hand { stroke: var(--accent); stroke-width: 2; stroke-linecap: round; }
	.mid { text-anchor: middle; font-size: 12px; fill: var(--ink); }
	@media (max-width: 560px) { .foot { grid-template-columns: 1fr; } }
</style>
