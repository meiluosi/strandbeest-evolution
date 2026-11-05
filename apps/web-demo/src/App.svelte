<script lang="ts">
import { call, download } from "./api";
import CommandPalette from "./CommandPalette.svelte";
import DesignTab from "./DesignTab.svelte";
import DigitalBeach from "./DigitalBeach.svelte";
import {
	currentDesign,
	editor,
	openDocument,
	redo,
	undo,
} from "./editor.svelte";
import FabTab from "./FabTab.svelte";
import Icon from "./Icon.svelte";
import { LOCALE_NAMES, LOCALES, type Locale } from "./i18n/core";
import { i18n, setLocale, t } from "./i18n/index.svelte";
import LabTab from "./LabTab.svelte";
import SimTab from "./SimTab.svelte";
import { designFromHash, REPO_URL, STATIC } from "./static";
import { setApi, store, view } from "./store.svelte";
import { theme, toggleTheme } from "./theme.svelte";

const allTabs = [
	["design", "nav.design", "nav.designSub", "design"],
	["evolve", "nav.evolve", "nav.evolveSub", "evolve"],
	["sim", "nav.sim", "nav.simSub", "sim"],
	["fab", "nav.fab", "nav.fabSub", "fab"],
	["beach", "nav.beach", "nav.beachSub", "beach"],
	["lab", "nav.lab", "nav.labSub", "lab"],
] as const;
type Tab = (typeof allTabs)[number][0];
const tabs = STATIC
	? allTabs.filter(([id]) => id !== "fab" && id !== "lab")
	: allTabs;
const primaryTabs = $derived(tabs.slice(0, 3));
const secondaryTabs = $derived(tabs.slice(3));

function initialTab(): Tab {
	if (typeof window !== "undefined") {
		const qTab = new URLSearchParams(window.location.search).get("tab");
		if (qTab && tabs.some(([id]) => id === qTab)) return qTab as Tab;
	}
	return "design";
}

let tab = $state<Tab>(initialTab());
let online = $state<"unknown" | "up" | "down">("unknown");
let paletteOpen = $state(false);
let editMessage = $state("");

$effect(() => {
	const current = tab;
	const url = new URL(window.location.href);
	if (url.searchParams.get("tab") === current) return;
	url.searchParams.set("tab", current);
	history.replaceState(null, "", url);
});

$effect(() => {
	if (typeof window !== "undefined") {
		const qLang = new URLSearchParams(window.location.search).get("lang");
		if (qLang && (LOCALES as readonly string[]).includes(qLang))
			setLocale(qLang as Locale);
		const qScroll = new URLSearchParams(window.location.search).get("scroll");
		if (qScroll === "glassbox") setTimeout(() => window.scrollTo(0, 560), 300);
	}
});

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

function runHistory(action: typeof undo) {
	if (tab !== "design") return;
	const result = action();
	editMessage = result.ok ? "" : (result.message ?? "");
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
		runHistory(e.shiftKey ? redo : undo);
	}
}

function navigate(next: Tab) {
	tab = next;
	editMessage = "";
	queueMicrotask(() =>
		document.getElementById("workspace")?.focus({ preventScroll: true }),
	);
}

function exportCurrent() {
	if (tab !== "design") return;
	download(`${view.name}.json`, JSON.stringify(currentDesign(), null, 2));
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
	if (!STATIC) return;
	designFromHash().then((doc: any) => {
		if (doc?.linkage?.params && Array.isArray(doc.linkage.joints))
			openDocument(doc);
	});
});
$effect(() => {
	if (STATIC) return;
	store.api;
	ping();
	const timer = setInterval(ping, 8000);
	return () => clearInterval(timer);
});
</script>

<div class="app-shell">
	<header class="project-bar">
		<div class="brand">
			<Icon name="logo" />
			<div>
				<h1 title={t("app.title")}>Strandbeest <span>Studio</span></h1>
				<small>{t("app.studioSubtitle")}</small>
				<span class="sr">{t("app.pipeline")}</span>
			</div>
		</div>
		<div class="project-context">
			<span class="project-kicker">{t("design.current")}</span>
			<strong title={view.designId}>{view.name}</strong>
			<span class:previewing={editor.preview !== null} class="save-state">
				<i></i>{editor.preview !== null ? t("app.previewing") : t("app.localHistory", { n: editor.steps.length })}
			</span>
		</div>
		<div class="project-actions">
			<div class="history-actions">
				<button class="icon-btn" aria-label={t("history.undo")} title={t("history.undo")} disabled={tab !== "design" || !editor.canUndo} onclick={() => runHistory(undo)}><Icon name="undo" /></button>
				<button class="icon-btn" aria-label={t("history.redo")} title={t("history.redo")} disabled={tab !== "design" || !editor.canRedo} onclick={() => runHistory(redo)}><Icon name="redo" /></button>
			</div>
			<button class="btn small command-button" onclick={() => { tab = "design"; paletteOpen = true; }}><Icon name="command" /><span>{t("palette.open")}</span><kbd>Ctrl K</kbd></button>
			{#if tab === "design"}<button class="icon-btn" aria-label={t("design.downloadJson")} title={t("design.downloadJson")} onclick={exportCurrent}><Icon name="download" /></button>{/if}
			<label class="lang">
				<span class="sr">{t("app.language")}</span>
				<select aria-label={t("app.language")} value={i18n.locale} onchange={(e) => { const locale = (e.target as HTMLSelectElement).value as Locale; setLocale(locale); const url = new URL(window.location.href); url.searchParams.set("lang", locale); history.replaceState(null, "", url); }}>
					{#each LOCALES as l}<option value={l}>{LOCALE_NAMES[l]}</option>{/each}
				</select>
			</label>
			<button class="icon-btn" aria-label={theme.mode === "dark" ? t("app.theme.light") : t("app.theme.dark")} title={theme.mode === "dark" ? t("app.theme.light") : t("app.theme.dark")} onclick={toggleTheme}><Icon name={theme.mode === "dark" ? "sun" : "moon"} /></button>
		</div>
	</header>

	<aside class="sidebar">
		<nav aria-label={t("nav.workspaces")}>
			<p class="nav-label">{t("nav.workspaces")}</p>
			{#each primaryTabs as [id, label, sub, icon]}
				<button class:active={tab === id} class="nav-item" aria-label={t(label)} aria-current={tab === id ? "page" : undefined} onclick={() => navigate(id)}>
					<Icon name={icon} /><span><b>{t(label)}</b><small>{t(sub)}</small></span><i class="nav-indicator"></i>
				</button>
			{/each}
			{#if secondaryTabs.length}
				<p class="nav-label secondary-label">{t("nav.more")}</p>
				{#each secondaryTabs as [id, label, sub, icon]}
					<button class:active={tab === id} class="nav-item secondary" aria-label={t(label)} aria-current={tab === id ? "page" : undefined} onclick={() => navigate(id)}>
						<Icon name={icon} /><span><b>{t(label)}</b><small>{t(sub)}</small></span><i class="nav-indicator"></i>
					</button>
				{/each}
			{/if}
		</nav>
		<div class="sidebar-footer">
			{#if !STATIC}
				<label class="api">
					<span class="backend-state"><i class="dot {online}"></i>{online === "up" ? t("app.backend.online") : online === "down" ? t("app.backend.offline") : t("app.backend.checking")}</span>
					<input aria-label={t("app.backend.address")} type="text" value={store.api} onchange={(e) => setApi((e.target as HTMLInputElement).value)} />
				</label>
			{:else}
				<span class="backend-state"><i class="dot up"></i>{t("app.static.mode")}</span>
			{/if}
		</div>
	</aside>

	<main id="workspace" class="workspace" tabindex="-1">
		{#if STATIC}
			<p class="notice environment-notice">{t("app.static.banner")} <a href={REPO_URL} target="_blank" rel="noreferrer">{t("app.static.local")}</a></p>
		{/if}
		{#if !STATIC && online === "down" && tab !== "design" && tab !== "evolve"}
			<p class="notice error environment-notice">{t("app.backend.unreachable.before", { api: store.api })} <code>strandbeest-api</code>{t("app.backend.unreachable.or")} <code>docker compose up</code>{t("app.backend.unreachable.after")}</p>
		{/if}
		{#if editMessage}<p class="notice error environment-notice">{editMessage}</p>{/if}
		{#if tab === "design" || tab === "evolve"}<DesignTab evolve={tab === "evolve"} oncommand={() => (paletteOpen = true)} onevolve={() => navigate("evolve")} onsim={() => navigate("sim")} />{:else if tab === "fab"}<FabTab />{:else if tab === "sim"}<SimTab />{:else if tab === "beach"}<DigitalBeach />{:else}<LabTab />{/if}
	</main>
</div>
<CommandPalette bind:open={paletteOpen} onmessage={(m) => (editMessage = m)} />
<svelte:window onkeydown={keys} />

<style>
	.app-shell { min-height: 100dvh; display: grid; grid-template-columns: 208px minmax(0, 1fr); grid-template-rows: 72px minmax(0, 1fr); }
	.project-bar { grid-column: 1 / -1; display: grid; grid-template-columns: 208px minmax(0, 1fr) auto; align-items: center; background: var(--surface-raised); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 20; }
	.brand { height: 100%; display: flex; align-items: center; gap: 11px; padding: 0 20px; border-right: 1px solid var(--line); }
	.brand :global(svg) { width: 28px; height: 28px; color: var(--accent); flex: 0 0 auto; }
	.brand h1 { font-size: 15px; letter-spacing: -0.035em; white-space: nowrap; }
	.brand h1 span { color: var(--accent-strong); }
	.brand small { display: block; margin-top: 2px; font-size: 10px; letter-spacing: 0.08em; }
	.project-context { min-width: 0; display: flex; align-items: center; gap: 12px; padding: 0 22px; }
	.project-kicker { color: var(--text-muted); font-size: 12px; white-space: nowrap; }
	.project-context strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
	.save-state { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 11px; white-space: nowrap; }
	.save-state i { width: 6px; height: 6px; border-radius: 50%; background: var(--success); }
	.save-state.previewing i { background: var(--accent); }
	.project-actions { display: flex; align-items: center; gap: 5px; padding-right: 16px; }
	.history-actions { display: flex; padding-right: 7px; margin-right: 3px; border-right: 1px solid var(--line); }
	.icon-btn { width: 36px; height: 36px; padding: 0; display: inline-grid; place-items: center; border: 1px solid transparent; border-radius: var(--radius-sm); background: transparent; color: var(--text-soft); cursor: pointer; }
	.icon-btn :global(svg), .command-button :global(svg) { width: 17px; height: 17px; }
	.icon-btn:hover:not(:disabled) { background: var(--surface-muted); color: var(--text); }
	.icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }
	.command-button { display: inline-flex; align-items: center; gap: 7px; }
	kbd { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
	.lang select { min-height: 36px; }
	.sidebar { grid-row: 2; position: sticky; top: 72px; align-self: start; height: calc(100dvh - 72px); display: flex; flex-direction: column; background: var(--surface); border-right: 1px solid var(--line); padding: 22px 12px 14px; }
	.sidebar nav { display: grid; gap: 5px; }
	.nav-label { margin: 0; padding: 0 11px 8px; color: var(--text-muted); font-size: 10px; font-weight: 600; letter-spacing: 0.12em; }
	.secondary-label { padding-top: 18px; }
	.nav-item { position: relative; width: 100%; min-height: 56px; display: flex; align-items: center; gap: 11px; padding: 9px 11px; border: 0; border-radius: 8px; background: transparent; color: var(--text); text-align: left; cursor: pointer; transition: background-color 160ms ease-out, color 160ms ease-out; }
	.nav-item :global(svg) { width: 20px; height: 20px; color: var(--text-muted); flex: 0 0 auto; }
	.nav-item > span { display: grid; gap: 1px; }
	.nav-item b { font-size: 13px; font-weight: 600; }
	.nav-item small { font-size: 11px; color: var(--text-muted); }
	.nav-item:hover { background: var(--surface-muted); }
	.nav-item.active { background: var(--accent-soft); color: var(--accent-strong); }
	.nav-item.active :global(svg), .nav-item.active small { color: var(--accent-strong); }
	.nav-indicator { position: absolute; right: -12px; width: 2px; height: 24px; border-radius: 2px; background: var(--accent); opacity: 0; }
	.nav-item.active .nav-indicator { opacity: 1; }
	.nav-item.secondary { min-height: 46px; }
	.sidebar-footer { margin-top: auto; padding: 14px 8px 0; border-top: 1px solid var(--line); }
	.api { width: 100%; gap: 8px; }
	.api input { width: 100%; font-family: var(--font-mono); font-size: 10px; }
	.backend-state { display: flex; align-items: center; gap: 7px; color: var(--text-muted); font-size: 11px; }
	.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex: 0 0 auto; }
	.dot.up { background: var(--ok); }
	.dot.down { background: var(--bad); }
	.workspace { min-width: 0; padding: 26px 28px 48px; outline: none; }
	.environment-notice { max-width: 1480px; margin: 0 auto 14px; }
	@media (max-width: 1120px) {
		.app-shell { grid-template-columns: 184px minmax(0, 1fr); }
		.project-bar { grid-template-columns: 184px minmax(0, 1fr) auto; }
		.brand { padding: 0 14px; }
		.project-context { padding: 0 14px; }
		.project-kicker, .save-state, .command-button kbd { display: none; }
		.workspace { padding: 22px 20px 40px; }
	}
	@media (max-width: 820px) {
		.app-shell { display: block; }
		.project-bar { grid-template-columns: minmax(0, 1fr) auto; min-height: 64px; }
		.brand { border-right: 0; }
		.brand small { display: none; }
		.project-context { grid-row: 2; grid-column: 1 / -1; padding: 8px 14px; border-top: 1px solid var(--line); }
		.project-kicker, .save-state { display: inline-flex; }
		.project-actions { padding-right: 10px; }
		.command-button span { display: none; }
		.sidebar { position: sticky; top: 105px; z-index: 15; width: 100%; height: auto; padding: 6px 10px; border-right: 0; border-bottom: 1px solid var(--line); }
		.sidebar nav { display: flex; gap: 4px; overflow-x: auto; }
		.nav-label, .nav-item small, .nav-indicator { display: none; }
		.nav-item, .nav-item.secondary { width: auto; min-width: 76px; min-height: 46px; justify-content: center; padding: 7px 12px; }
		.nav-item > span { display: block; }
		.sidebar-footer { display: none; }
		.workspace { padding: 20px 16px 40px; }
	}
	@media (max-width: 480px) {
		.brand { padding-left: 12px; }
		.brand h1 { font-size: 13px; }
		.brand :global(svg) { width: 23px; height: 23px; }
		.history-actions { padding-right: 2px; margin-right: 0; }
		.project-actions { gap: 1px; }
		.command-button { display: none; }
		.icon-btn { width: 40px; height: 40px; }
		.lang select { width: 62px; padding: 4px; }
		.project-context { gap: 8px; }
		.project-kicker { display: none; }
		.save-state { margin-left: auto; }
		.sidebar { top: 105px; }
		.nav-item, .nav-item.secondary { min-width: 70px; padding: 7px 9px; }
		.workspace { padding: 16px 12px 32px; }
	}
</style>
