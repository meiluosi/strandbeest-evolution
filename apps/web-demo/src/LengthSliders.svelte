<script lang="ts">
import type { JansenParams } from "strandbeest-core";

let { params = $bindable() }: { params: JansenParams } = $props();

const groups: {
	title: string;
	hint: string;
	items: [keyof JansenParams, string][];
}[] = [
	{
		title: "曲柄与机架",
		hint: "决定脚轨迹的整体大小",
		items: [
			["m", "曲柄长"],
			["a", "曲柄轴 x"],
			["l", "曲柄轴 y"],
		],
	},
	{
		title: "上部三角",
		hint: "把曲柄的圆周运动传给下肢",
		items: [
			["b", "G–K"],
			["d", "G–L"],
			["e", "K–L"],
			["j", "C–K"],
		],
	},
	{
		title: "下肢",
		hint: "决定脚轨迹的形状（平底还是圆）",
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
			<h3>{g.title} <small>{g.hint}</small></h3>
			{#each g.items as [name, role]}
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
