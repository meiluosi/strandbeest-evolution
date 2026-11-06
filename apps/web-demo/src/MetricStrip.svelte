<script lang="ts" module>
export type MetricItem = {
	key: string;
	label: string;
	value: string;
	detail?: string;
	valueClass?: string;
};
</script>

<script lang="ts">
let {
	items,
	label,
	note = "",
	variant = "geometry",
}: {
	items: MetricItem[];
	label: string;
	note?: string;
	variant?: "geometry" | "run";
} = $props();
</script>

<div class="metric-strip" class:run-metrics={variant === "run"} aria-label={label}>
	{#each items as item (item.key)}
		<div class="metric">
			<b class={item.valueClass}>{item.value}</b>
			<span>{item.label}</span>
			{#if item.detail}<small>{item.detail}</small>{/if}
		</div>
	{/each}
	{#if note}<p>{note}</p>{/if}
</div>

<style>
	.metric-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; border-top: 1px solid var(--line); background: var(--line); }
	.metric { display: flex; min-width: 0; flex-direction: column; gap: 3px; padding: 14px 16px; background: var(--surface-raised); }
	.metric b { min-width: 0; font-family: var(--font-mono); font-size: 21px; font-weight: 500; line-height: 1.15; overflow-wrap: anywhere; }
	.metric span { color: var(--text-muted); font-size: 10px; }
	.metric small { color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; }
	.metric-strip > p { grid-column: 1 / -1; margin: 0; padding: 7px 16px; background: var(--surface-raised); color: var(--text-faint); font-size: 10px; }
	.run-metrics { margin: 18px 0; border: 1px solid var(--line); border-radius: var(--radius-sm); overflow: hidden; }
	.run-metrics .metric { padding: 16px; }
	.run-metrics .metric b { font-size: clamp(18px, 2vw, 25px); }
	@media (max-width: 600px) {
		.metric { padding: 12px 10px; }
		.metric b { font-size: 18px; }
	}
	@media (max-width: 520px) {
		.run-metrics { grid-template-columns: minmax(0, 1fr); }
		.run-metrics .metric { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; padding: 10px 12px; }
		.run-metrics .metric b { grid-column: 2; grid-row: 1; }
		.run-metrics .metric small { grid-column: 2; }
	}
</style>
