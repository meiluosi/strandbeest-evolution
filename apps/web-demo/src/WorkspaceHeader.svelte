<script lang="ts">
import type { Snippet } from "svelte";

let {
	eyebrow,
	title,
	description,
	actions,
}: {
	eyebrow: string;
	title: string;
	description: string;
	actions?: Snippet;
} = $props();
</script>

<header class="workspace-header">
	<div class="workspace-heading">
		<p class="eyebrow">{eyebrow}</p>
		<h2>{title}</h2>
		<p class="workspace-description">{description}</p>
	</div>
	{#if actions}<div class="workspace-actions">{@render actions()}</div>{/if}
</header>

<style>
	.workspace-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
	.workspace-heading { max-width: 780px; }
	.eyebrow { margin: 0 0 5px; color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; font-weight: 600; letter-spacing: 0.13em; }
	h2 { margin-top: 4px; font-size: clamp(24px, 2.3vw, 32px); letter-spacing: -0.04em; }
	.workspace-description { margin-top: 6px; color: var(--text-soft); font-size: 13px; line-height: 1.65; }
	.workspace-actions { display: flex; gap: 8px; flex: 0 0 auto; }
	.workspace-actions :global(.btn) { display: inline-flex; align-items: center; justify-content: center; gap: 7px; }
	.workspace-actions :global(svg) { width: 15px; height: 15px; }
	@media (max-width: 600px) {
		.workspace-header { align-items: flex-start; flex-direction: column; gap: 14px; margin-bottom: 16px; }
		.workspace-actions { width: 100%; }
		.workspace-actions :global(.btn) { flex: 1; }
	}
</style>
