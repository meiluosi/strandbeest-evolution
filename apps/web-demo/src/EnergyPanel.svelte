<script lang="ts">
import { t } from "./i18n/index.svelte";
import type { Replay } from "./replay-types";

/** Energy flow (Sankey) per revolution and the invariants of the run; a number past its limit turns red. The numbers are the
 * run's own metrics (strandbeest_sim.metrics_builtin), so they are the same everywhere. */
let { replay }: { replay: Replay } = $props();
const m = $derived(replay.metrics);

// limits: choices, not physics (docs/EXPERIMENTS.md 14)
const LIMITS = {
	loop: [0.001, 0.005],
	penetration: [0.003, 0.005],
	residual: [0.01, 0.02],
} as const;
const level = (
	v: number | null | undefined,
	[warn, bad]: readonly [number, number],
) =>
	v == null || Number.isNaN(v)
		? "na"
		: Math.abs(v) > bad
			? "bad"
			: Math.abs(v) > warn
				? "warn"
				: "ok";

const inputJ = $derived(m.energy_in_per_rev ?? null);
const flows = $derived.by(() => {
	if (inputJ == null) return [];
	const contact = m.energy_contact_share ?? 0;
	const loops = m.energy_loops_share ?? 0;
	const friction = m.energy_friction_share ?? 0;
	const rest = 1 - contact - loops - friction; // change of kinetic + potential energy and the residual
	return [
		{ id: "contact", share: contact, color: "#d9622b" },
		{ id: "loops", share: loops, color: "#6b7fd7" },
		{ id: "friction", share: friction, color: "#8a8a8a" },
		{ id: "stored", share: rest, color: "#2e8b57" },
	].filter((f) => Math.abs(f.share) > 0.0005);
});
const H = 140;
const bands = $derived.by(() => {
	let yIn = 10;
	let yOut = 10;
	const total = flows.reduce((s, f) => s + Math.max(f.share, 0), 0) || 1;
	const scale = (H - 20 - 6 * (flows.length - 1)) / total;
	return flows.map((f) => {
		const h = Math.max(f.share, 0) * scale;
		const b = { ...f, h, y0: yIn, y1: yOut };
		yIn += h;
		yOut += h + 6;
		return b;
	});
});
const path = (b: { y0: number; y1: number; h: number }) =>
	`M 80 ${b.y0} C 180 ${b.y0}, 180 ${b.y1}, 280 ${b.y1} L 280 ${b.y1 + b.h} C 180 ${b.y1 + b.h}, 180 ${b.y0 + b.h}, 80 ${b.y0 + b.h} Z`;
const FLOW_LABELS = {
	contact: "energy.contact",
	loops: "energy.loops",
	friction: "energy.friction",
	stored: "energy.stored",
} as const;
const steady = $derived(m.steady_window === 1);
</script>

<div class="energy">
	<div>
		<h4>{t("energy.title")}</h4>
		{#if inputJ == null}
			<p class="muted">{t("energy.none")}</p>
		{:else}
			<svg viewBox="0 0 400 {H}" role="img" aria-label={t("energy.title")}>
				<rect x="60" y="10" width="20" height={H - 20} fill="var(--accent)" />
				<text x="56" y={H / 2} class="in" text-anchor="end">{(inputJ * 1000).toFixed(2)} mJ</text>
				{#each bands as b}
					<path d={path(b)} fill={b.color} opacity="0.55" />
					<text x="286" y={b.y1 + Math.max(b.h, 12) / 2 + 4} class="lab">{t(FLOW_LABELS[b.id as keyof typeof FLOW_LABELS])} {(b.share * 100).toFixed(1)}% · {(b.share * inputJ * 1000).toFixed(2)} mJ</text>
				{/each}
			</svg>
			<small class="muted">{t("energy.caption", { revs: (m.energy_window_revs ?? 0).toFixed(1) })} {steady ? "" : t("energy.notSteady")}</small>
		{/if}
	</div>
	<div>
		<h4>{t("invariants.title")}</h4>
		<table>
			<tbody>
				<tr class={level(m.max_loop_violation, LIMITS.loop)}><td>{t("invariants.loop")}</td><td>{((m.max_loop_violation ?? 0) * 1000).toFixed(2)} mm</td><td>{t("invariants.limit", { limit: "5 mm" })}</td></tr>
				<tr class={level(m.max_penetration, LIMITS.penetration)}><td>{t("invariants.penetration")}</td><td>{((m.max_penetration ?? 0) * 1000).toFixed(2)} mm</td><td>{t("invariants.limit", { limit: "5 mm" })}</td></tr>
				<tr class={steady ? level(m.energy_residual_share, LIMITS.residual) : "na"}><td>{t("invariants.residual")}</td><td>{m.energy_residual_share == null ? "–" : `${(m.energy_residual_share * 100).toFixed(2)}%`}</td><td>{t("invariants.limit", { limit: "2%" })}</td></tr>
			</tbody>
		</table>
	</div>
</div>

<style>
	.energy { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; }
	h4 { margin: 0 0 4px; }
	svg { width: 100%; max-width: 460px; }
	.in { font-size: 11px; fill: var(--ink); }
	.lab { font-size: 11px; fill: var(--ink); }
	table { border-collapse: collapse; width: 100%; font-size: 13px; }
	td { padding: 4px 6px; border-bottom: 1px solid var(--line); }
	tr.ok td:nth-child(2) { color: #2e8b57; font-weight: 600; }
	tr.warn td:nth-child(2) { color: #c98a00; font-weight: 600; }
	tr.bad { background: #d6282822; }
	tr.bad td:nth-child(2) { color: #d62828; font-weight: 700; }
	tr.na td { color: var(--muted); }
	@media (max-width: 640px) { .energy { grid-template-columns: 1fr; } }
</style>
