<script lang="ts">
import { t } from "./i18n/index.svelte";
import type { Replay, RunEvent } from "./replay-types";

/** Event lanes along the run's time axis; a click on an event jumps the replay to it. */
let {
	replay,
	time,
	onseek,
}: { replay: Replay; time: number; onseek: (t: number) => void } = $props();

const W = 600;
const t1 = $derived(
	Math.max(replay.series.t.at(-1) as number, replay.t.at(-1) as number, 1e-9),
);
const x = (tt: number) => 8 + (tt / t1) * (W - 16);

const LANES = [
	{ id: "state", kinds: ["start", "stall"], label: "timeline.state" },
	{
		id: "torque_limit",
		kinds: ["torque_limit"],
		label: "timeline.torque_limit",
	},
	{ id: "loop_open", kinds: ["loop_open"], label: "timeline.loop_open" },
	{ id: "slip", kinds: ["slip"], label: "timeline.slip" },
	{ id: "gust", kinds: ["gust"], label: "timeline.gust" },
	{ id: "steps", kinds: ["touchdown", "liftoff"], label: "timeline.steps" },
] as const;
const lanes = $derived(
	LANES.map((l) => ({
		...l,
		events: replay.events.filter((e) =>
			(l.kinds as readonly string[]).includes(e.kind),
		),
	})).filter((l) => l.events.length),
);
const KIND_LABELS: Record<string, string> = {
	start: "event.start",
	stall: "event.stall",
	touchdown: "event.touchdown",
	liftoff: "event.liftoff",
	slip: "event.slip",
	torque_limit: "event.torque_limit",
	loop_open: "event.loop_open",
	gust: "event.gust",
};
const COLORS: Record<string, string> = {
	start: "#2e8b57",
	stall: "#d62828",
	touchdown: "#2e8b57",
	liftoff: "#d9622b",
	slip: "#d62828",
	torque_limit: "#c98a00",
	loop_open: "#d62828",
	gust: "#4a7bd0",
};
const name = (e: RunEvent) =>
	`${t(KIND_LABELS[e.kind] ?? "event.other")}${e.leg != null ? ` ${e.leg + 1}` : ""} · ${e.t.toFixed(2)} s`;
const rowH = 16;
</script>

<div class="timeline">
	{#if lanes.length === 0}
		<p class="muted">{t("timeline.none")}</p>
	{:else}
		<svg viewBox="0 0 {W} {lanes.length * rowH + 6}" role="group" aria-label={t("timeline.title")}>
			{#each lanes as lane, i}
				<text x="6" y={i * rowH + 11} class="lab">{t(lane.label)}</text>
				<line x1="8" x2={W - 8} y1={i * rowH + rowH - 2} y2={i * rowH + rowH - 2} class="axis" />
				{#each lane.events as e}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<rect x={x(e.t) - 2} y={i * rowH + 2} width={e.detail?.duration_s ? Math.max(4, x(e.t + e.detail.duration_s) - x(e.t)) : 4} height={rowH - 5} fill={COLORS[e.kind] ?? "#888"} class="ev" onclick={() => onseek(e.t)}><title>{name(e)}</title></rect>
				{/each}
			{/each}
			<line x1={x(time)} x2={x(time)} y1="0" y2={lanes.length * rowH} class="cursor" />
		</svg>
	{/if}
</div>

<style>
	svg { width: 100%; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); }
	.lab { font-size: 9px; fill: var(--muted); paint-order: stroke; stroke: var(--bg); stroke-width: 3px; }
	.axis { stroke: var(--line); stroke-width: 0.5; }
	.ev { cursor: pointer; opacity: 0.85; }
	.ev:hover { opacity: 1; }
	.cursor { stroke: var(--accent); stroke-width: 1.2; }
</style>
