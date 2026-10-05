<script lang="ts">
import { call } from "./api";
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
let online = $state<"unknown" | "up" | "down">("unknown");

async function ping() {
	try {
		await call("/health");
		online = "up";
	} catch {
		online = "down";
	}
}
$effect(() => {
	store.api;
	ping();
	const t = setInterval(ping, 8000);
	return () => clearInterval(t);
});
</script>

<header>
	<div class="wrap top">
		<div>
			<h1>Strandbeest 设计与验证平台</h1>
			<small>设计 → 仿真 → 3D 打印 → 测量 → 校准</small>
		</div>
		<label class="api">
			<span><i class="dot {online}"></i>{online === "up" ? "后端在线" : online === "down" ? "后端未连接" : "检查后端…"}</span>
			<input type="text" size="22" value={store.api} onchange={(e) => setApi((e.target as HTMLInputElement).value)} />
		</label>
	</div>
	<nav class="wrap">
		{#each tabs as [id, label]}
			<button class:active={tab === id} onclick={() => (tab = id)}>{label}</button>
		{/each}
	</nav>
</header>
<main class="wrap">
	{#if online === "down" && tab !== "design"}
		<p class="notice error">连不上后端 {store.api}。在项目目录运行 <code>strandbeest-api</code>（或 <code>docker compose up</code>），设计页不需要后端。</p>
	{/if}
	{#if tab === "design"}<DesignTab />{:else if tab === "fab"}<FabTab />{:else if tab === "sim"}<SimTab />{:else}<LabTab />{/if}
</main>

<style>
	.wrap { max-width: 1040px; margin: 0 auto; padding: 0 16px; }
	header { background: var(--card); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 5; }
	.top { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding-top: 12px; padding-bottom: 6px; flex-wrap: wrap; }
	nav { display: flex; gap: 4px; }
	nav button { font: inherit; border: none; background: transparent; color: var(--muted); padding: 8px 16px; cursor: pointer; border-bottom: 2px solid transparent; }
	nav button:hover { color: var(--ink); }
	nav button.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
	main { padding-top: 16px; padding-bottom: 40px; }
	.api { align-items: flex-end; }
	.api input { font-size: 12px; }
	.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--muted); margin-right: 5px; }
	.dot.up { background: var(--ok); }
	.dot.down { background: var(--bad); }
</style>
