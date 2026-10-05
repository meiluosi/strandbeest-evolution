<script lang="ts">
import type { JansenParams } from "strandbeest-core";
import { t } from "./i18n/index.svelte";

let { params = $bindable() }: { params: JansenParams } = $props();

const groups: {
	title: string;
	hint: string;
	items: [keyof JansenParams, string][];
}[] = [
	{
		title: "sliders.crank",
		hint: "sliders.crank.hint",
		items: [
			["m", "sliders.crankLength"],
			["a", "sliders.crankX"],
			["l", "sliders.crankY"],
		],
	},
	{
		title: "sliders.upper",
		hint: "sliders.upper.hint",
		items: [
			["b", "G–K"],
			["d", "G–L"],
			["e", "K–L"],
			["j", "C–K"],
		],
	},
	{
		title: "sliders.lower",
		hint: "sliders.lower.hint",
		items: [
			["c", "G–M"],
			["k", "C–M"],
			["f", "L–N"],
			["g", "M–N"],
			["i", "M–F"],
			["h", "N–F"],
		],
	},
];
</script>

<div class="stack">
	{#each groups as g}
		<div>
			<h3>{t(g.title)} <small>{t(g.hint)}</small></h3>
			{#each g.items as [name, rawRole]}
				{@const role = rawRole.startsWith("sliders.") ? t(rawRole) : rawRole}
				<div class="s">
					<span class="n" title={role}>{name}<small> {role}</small></span>
					<input type="range" min="1" max="100" step="0.1" bind:value={params[name]} />
					<input type="number" min="1" max="100" step="0.1" bind:value={params[name]} />
				</div>
			{/each}
		</div>
	{/each}
</div>


<style>
	.s { display: grid; grid-template-columns: 112px 1fr 64px; gap: 8px; align-items: center; margin: 3px 0; }
	.n { font-weight: 600; white-space: nowrap; }
	.n small { margin-left: 6px; font-weight: 400; }
	input[type="number"] { width: 64px; padding: 2px 5px; }
</style>