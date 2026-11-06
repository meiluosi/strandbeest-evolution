<script lang="ts">
let {
	name,
}: {
	name:
		| "logo"
		| "research"
		| "protocol"
		| "runs"
		| "evidence"
		| "design"
		| "evolve"
		| "sim"
		| "fab"
		| "beach"
		| "lab"
		| "undo"
		| "redo"
		| "download"
		| "command"
		| "moon"
		| "sun";
} = $props();
</script>

<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
	{#if name === "logo"}
		<circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="m8 7 8 10M16 7 8 17M8.5 6h7M6 8.5v7M18 8.5v7" />
	{:else if name === "research"}
		<circle cx="12" cy="12" r="3" /><circle cx="12" cy="12" r="8" /><path d="M4 12H2m20 0h-2M12 4V2m0 20v-2" />
	{:else if name === "protocol"}
		<path d="M6 3h12v18H6zM9 7h6M9 11h6M9 15h3" /><path d="M9 3V1h6v2" />
	{:else if name === "runs"}
		<circle cx="12" cy="12" r="9" /><path d="m10 8 6 4-6 4Z" /><path d="M12 3v2M21 12h-2M12 21v-2M3 12h2" />
	{:else if name === "evidence"}
		<path d="M4 19V5m0 14h16" /><path d="m7 15 4-4 3 2 5-7" /><circle cx="7" cy="15" r="1" /><circle cx="11" cy="11" r="1" /><circle cx="14" cy="13" r="1" /><circle cx="19" cy="6" r="1" />
	{:else if name === "design"}
		<path d="m14 6 4 4L8 20l-5 1 1-5Z" /><path d="m13 7 4 4M4 16l4 4" /><circle cx="17" cy="5" r="2" />
	{:else if name === "evolve"}
		<path d="M4 17c2-8 5 2 8-6s5 2 8-6" /><path d="M4 21h16M4 3v18" />
	{:else if name === "sim"}
		<path d="M3 12h4l2-7 4 14 2-7h6" />
	{:else if name === "fab"}
		<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" />
	{:else if name === "beach"}
		<path d="M3 16c3-3 5 3 9 0s6 3 9 0M3 20c3-3 5 3 9 0s6 3 9 0M12 3v10M12 4c5 0 7 2 8 5H4c1-3 3-5 8-5Z" />
	{:else if name === "lab"}
		<path d="M9 3h6M10 3v6l-5 9c-.7 1.3.1 3 1.7 3h10.6c1.6 0 2.4-1.7 1.7-3l-5-9V3" /><path d="M7 16h10" />
	{:else if name === "undo" || name === "redo"}
		<path d={name === "undo" ? "M9 7 4 12l5 5M5 12h8a6 6 0 0 1 6 6" : "m15 7 5 5-5 5m4-5h-8a6 6 0 0 0-6 6"} />
	{:else if name === "download"}
		<path d="M12 3v12m-5-5 5 5 5-5M4 20h16" />
	{:else if name === "command"}
		<path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3Z" />
	{:else if name === "moon"}
		<path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z" />
	{:else}
		<circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M19 5l-1.5 1.5m-11 11L5 19" />
	{/if}
</svg>
