<script lang="ts">
let {
	label,
	tone = "neutral",
	state,
	live = false,
	className = "",
}: {
	label: string;
	tone?: "neutral" | "info" | "success" | "accent" | "danger";
	state?: string;
	live?: boolean;
	className?: string;
} = $props();
</script>

<span class="state-badge {tone} {className}" data-state={state} role={live ? "status" : undefined}>
	<i aria-hidden="true"></i>{label}
</span>

<style>
	.state-badge { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 25px; padding: 3px 9px; border: 1px solid var(--line); border-radius: 999px; background: var(--neutral-soft); color: var(--text-muted); font-size: 10px; line-height: 1.35; white-space: nowrap; }
	.state-badge i { width: 5px; height: 5px; flex: 0 0 auto; border-radius: 50%; background: currentColor; }
	.state-badge.info { border-color: color-mix(in srgb, var(--info) 24%, transparent); background: var(--info-soft); color: var(--info); }
	.state-badge.success { border-color: color-mix(in srgb, var(--success) 24%, transparent); background: var(--success-soft); color: var(--success); }
	.state-badge.accent { border-color: color-mix(in srgb, var(--accent) 24%, transparent); background: var(--accent-soft); color: var(--accent-strong); }
	.state-badge.danger { border-color: color-mix(in srgb, var(--danger) 24%, transparent); background: var(--danger-soft); color: var(--danger); }
	@media (max-width: 480px) {
		.state-badge { white-space: normal; text-align: left; }
	}
</style>
