<script lang="ts">
import { call } from "./api";
import CommandPalette from "./CommandPalette.svelte";
import DesignTab from "./DesignTab.svelte";
import { redo, undo } from "./editor.svelte";
import FabTab from "./FabTab.svelte";
import { LOCALE_NAMES, LOCALES } from "./i18n/core";
import { i18n, setLocale, t } from "./i18n/index.svelte";
import LabTab from "./LabTab.svelte";
import SimTab from "./SimTab.svelte";
import { setApi, store } from "./store.svelte";

const tabs = [
	["design", "nav.design"],
	["fab", "nav.fab"],
	["sim", "nav.sim"],
	["lab", "nav.lab"],
] as const;
let tab = $state<(typeof tabs)[number][0]>("design");
let online = $state<"unknown" | "up" | "down">("unknown");
let paletteOpen = $state(false);
let editMessage = $state("");

function typing(e: KeyboardEvent): boolean {
	const el = e.target as HTMLElement | null;
	return (
		!!el &&
		(el.tagName === "INPUT" ||
			el.tagName === "TEXTAREA" ||
			el.tagName === "SELECT" ||
			el.isContentEditable)
	);
}

function keys(e: KeyboardEvent) {
	const mod = e.metaKey || e.ctrlKey;
	if (mod && e.key.toLowerCase() === "k") {
		e.preventDefault();
		tab = "design";
		paletteOpen = !paletteOpen;
	} else if (
		mod &&
		e.key.toLowerCase() === "z" &&
		!typing(e) &&
		tab === "design"
	) {
		e.preventDefault();
		const r = e.shiftKey ? redo() : undo();
		editMessage = r.ok ? "" : (r.message ?? "");
	}
}

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
	const timer = setInterval(ping, 8000);
	return () => clearInterval(timer);
});
</script>

<header>
	<div class="wrap top">
		<div>
			<h1>{t("app.title")}</h1>
			<small>{t("app.pipeline")}</small>
		</div>
		<label class="lang">
			<span class="sr">{t("app.language")}</span>
			<select value={i18n.locale} onchange={(e) => setLocale((e.target as HTMLSelectElement).value as (typeof LOCALES)[number])}>
				{#each LOCALES as l}<option value={l}>{LOCALE_NAMES[l]}</option>{/each}
			</select>
		</label>
		<label class="api">
			<span><i class="dot {online}"></i>{online === "up" ? t("app.backend.online") : online === "down" ? t("app.backend.offline") : t("app.backend.checking")}</span>
			<input type="text" size="22" value={store.api} onchange={(e) => setApi((e.target as HTMLInputElement).value)} />
		</label>
	</div>
	<nav class="wrap">
		{#each tabs as [id, label]}
			<button class:active={tab === id} onclick={() => (tab = id)}>{t(label)}</button>
		{/each}
	</nav>
</header>
<main class="wrap">
	{#if online === "down" && tab !== "design"}
		<p class="notice error">{t("app.backend.unreachable.before", { api: store.api })} <code>strandbeest-api</code>{t("app.backend.unreachable.or")} <code>docker compose up</code>{t("app.backend.unreachable.after")}</p>
	{/if}
	{#if editMessage}<p class="notice error">{editMessage}</p>{/if}
	{#if tab === "design"}<DesignTab oncommand={() => (paletteOpen = true)} />{:else if tab === "fab"}<FabTab />{:else if tab === "sim"}<SimTab />{:else}<LabTab />{/if}
</main>
<CommandPalette bind:open={paletteOpen} onmessage={(m) => (editMessage = m)} />
<svelte:window onkeydown={keys} />


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