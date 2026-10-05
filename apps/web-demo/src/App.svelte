<script lang="ts">
import DesignTab from "./DesignTab.svelte";
import FabTab from "./FabTab.svelte";
import LabTab from "./LabTab.svelte";
import SimTab from "./SimTab.svelte";
import { setApi, store } from "./store.svelte";

const tabs = [
	["design", "设计"],
	["fab", "制造"],
	["sim", "仿真"],
	["lab", "实验室"],
] as const;
let tab = $state<(typeof tabs)[number][0]>("design");
</script>

<main>
	<h1>Strandbeest 设计与验证平台</h1>
	<nav>
		{#each tabs as [id, label]}
			<button class:active={tab === id} onclick={() => (tab = id)}>{label}</button>
		{/each}
		<label class="api">后端 <input type="text" size="22" value={store.api} onchange={(e) => setApi((e.target as HTMLInputElement).value)} /></label>
	</nav>
	{#if tab === "design"}<DesignTab />{:else if tab === "fab"}<FabTab />{:else if tab === "sim"}<SimTab />{:else}<LabTab />{/if}
</main>

<style>
	:global(body) { font-family: system-ui, sans-serif; margin: 0; background: Canvas; color: CanvasText; color-scheme: light dark; }
	main { max-width: 900px; margin: 0 auto; padding: 16px; }
	nav { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; border-bottom: 1px solid #8884; padding-bottom: 8px; margin-bottom: 8px; }
	nav button { padding: 6px 14px; border: 1px solid #8886; border-radius: 6px 6px 0 0; background: transparent; color: inherit; cursor: pointer; }
	nav button.active { background: #e5733f33; font-weight: 600; }
	.api { margin-left: auto; font-size: 12px; }
</style>
