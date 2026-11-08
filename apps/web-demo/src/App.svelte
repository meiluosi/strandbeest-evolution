<script lang="ts">
import type { LinkageSpec } from "strandbeest-core";
import { call, download } from "./api";
import CommandPalette from "./CommandPalette.svelte";
import DesignTab from "./DesignTab.svelte";
import DigitalBeach from "./DigitalBeach.svelte";
import EvolveTab from "./EvolveTab.svelte";
import {
	branchDesign,
	commit,
	currentDesign,
	editor,
	op,
	openDocument,
	redo,
	undo,
} from "./editor.svelte";
import FabTab from "./FabTab.svelte";
import Icon from "./Icon.svelte";
import { LOCALE_NAMES, LOCALES, type Locale } from "./i18n/core";
import { i18n, setLocale, t } from "./i18n/index.svelte";
import LabTab from "./LabTab.svelte";
import ResearchTab, { type ResearchView } from "./ResearchTab.svelte";
import SimTab from "./SimTab.svelte";
import { designFromHash, REPO_URL, STATIC } from "./static";
import { setApi, store, view } from "./store.svelte";
import { theme, toggleTheme } from "./theme.svelte";

const researchTabs = [
	["research", "nav.research", "nav.researchSub", "research"],
] as const;
const domainTabs = [
	["design", "nav.design", "nav.designSub", "design"],
	["evolve", "nav.evolve", "nav.evolveSub", "evolve"],
	["sim", "nav.sim", "nav.simSub", "sim"],
] as const;
const secondaryTabs = [
	["fab", "nav.fab", "nav.fabSub", "fab"],
	["beach", "nav.beach", "nav.beachSub", "beach"],
	["lab", "nav.lab", "nav.labSub", "lab"],
] as const;
const allTabs = [...researchTabs, ...domainTabs, ...secondaryTabs] as const;
type Tab = (typeof allTabs)[number][0];
const visibleSecondaryTabs = STATIC
	? secondaryTabs.filter(([id]) => id !== "fab" && id !== "lab")
	: secondaryTabs;

function initialTab(): Tab {
	if (typeof window !== "undefined") {
		const qTab = new URLSearchParams(window.location.search).get("tab");
		if (qTab && allTabs.some(([id]) => id === qTab)) return qTab as Tab;
	}
	return "design";
}

function initialResearchView(): ResearchView {
	if (typeof window !== "undefined") {
		const value = new URLSearchParams(window.location.search).get("view");
		if (value === "runs" || value === "evidence") return value;
	}
	return "protocol";
}

function initialResearchIdentity(key: "experiment" | "revision"): string {
	return typeof window === "undefined"
		? ""
		: (new URLSearchParams(window.location.search).get(key) ?? "");
}

let tab = $state<Tab>(initialTab());
let researchView = $state<ResearchView>(initialResearchView());
let researchExperiment = $state(initialResearchIdentity("experiment"));
let researchRevision = $state(initialResearchIdentity("revision"));
let researchTitle = $state("");
let online = $state<"unknown" | "up" | "down">("unknown");
let paletteOpen = $state(false);
let editMessage = $state("");

$effect(() => {
	const current = tab;
	const currentResearchView = researchView;
	const experiment = researchExperiment;
	const revision = researchRevision;
	const url = new URL(window.location.href);
	if (url.searchParams.get("tab") !== current)
		url.searchParams.set("tab", current);
	if (current === "research") {
		url.searchParams.set("view", currentResearchView);
		if (experiment) url.searchParams.set("experiment", experiment);
		else url.searchParams.delete("experiment");
		if (revision) url.searchParams.set("revision", revision);
		else url.searchParams.delete("revision");
	} else {
		url.searchParams.delete("view");
		url.searchParams.delete("experiment");
		url.searchParams.delete("revision");
	}
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

function navigateResearch(next: ResearchView) {
	researchView = next;
	tab = "research";
}

function selectResearch(experiment: string, revision: string, title: string) {
	researchExperiment = experiment;
	researchRevision = revision;
	researchTitle = title;
}

function exportCurrent() {
	if (tab !== "design") return;
	download(`${view.name}.json`, JSON.stringify(currentDesign(), null, 2));
}

function applyEvolved(spec: LinkageSpec) {
	const parent = currentDesign();
	const now = parent.linkage.params;
	const ops = Object.entries(spec.params)
		.filter(([key, value]) => now[key] !== value)
		.map(([key, value]) =>
			op("set_param", { name: key, value }, "evolver: best of the run", {
				kind: "algorithm",
				id: "ga",
			}),
		);
	if (!ops.length) return;
	branchDesign(`${parent.name}-evolved`);
	const result = commit(ops);
	editMessage = result.ok ? "" : (result.message ?? "");
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

<div class="app-shell" data-context={tab === "research" ? "research" : "design"}>
	<header class="project-bar">
		<div class="brand">
			<span class="brand-mark"><Icon name="logo" /></span>
			<div>
				<h1 title={t("app.title")}>Beest <span>Harness</span></h1>
				<small>{t("app.studioSubtitle")}</small>
				<span class="sr">{t("app.pipeline")}</span>
			</div>
		</div>
		<div class="project-context">
			<span class="context-symbol"><Icon name={tab === "research" ? "research" : "design"} /></span>
			<div class="context-copy">
				<span class="project-kicker">{tab === "research" ? t("research.context") : t("design.current")}</span>
				<strong title={tab === "research" ? (researchTitle || t("research.noExperimentShort")) : view.designId}>
					{tab === "research" ? (researchTitle || t("research.noExperimentShort")) : view.name}
				</strong>
			</div>
			{#if tab === "research"}
				<span class="research-context-state"><i></i>{t("research.manualTrack")}</span>
			{:else}
				<span class:previewing={editor.preview !== null} class="save-state">
					<i></i>{editor.preview !== null ? t("app.previewing") : t("app.localHistory", { n: editor.steps.length })}
				</span>
			{/if}
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
			<section class="nav-group research-group" aria-labelledby="research-nav-label">
				<p class="nav-label" id="research-nav-label">{t("nav.researchGroup")}</p>
				{#each researchTabs as [id, label, sub, icon]}
					<button class:active={tab === id} class="nav-item research" aria-label={t(label)} aria-current={tab === id ? "page" : undefined} onclick={() => navigate(id)}>
						<Icon name={icon} /><span><b>{t(label)}</b><small>{t(sub)}</small></span><i class="nav-indicator"></i>
					</button>
				{/each}
			</section>
			<section class="nav-group" aria-labelledby="domain-nav-label">
				<p class="nav-label" id="domain-nav-label">{t("nav.domainGroup")}</p>
				{#each domainTabs as [id, label, sub, icon]}
					<button class:active={tab === id} class="nav-item" aria-label={t(label)} aria-current={tab === id ? "page" : undefined} onclick={() => navigate(id)}>
						<Icon name={icon} /><span><b>{t(label)}</b><small>{t(sub)}</small></span><i class="nav-indicator"></i>
					</button>
				{/each}
			</section>
			{#if visibleSecondaryTabs.length}
				<section class="nav-group secondary-group" aria-labelledby="secondary-nav-label">
					<p class="nav-label" id="secondary-nav-label">{t("nav.more")}</p>
					{#each visibleSecondaryTabs as [id, label, sub, icon]}
						<button class:active={tab === id} class="nav-item secondary" aria-label={t(label)} aria-current={tab === id ? "page" : undefined} onclick={() => navigate(id)}>
							<Icon name={icon} /><span><b>{t(label)}</b><small>{t(sub)}</small></span><i class="nav-indicator"></i>
						</button>
					{/each}
				</section>
			{/if}
		</nav>
		<div class="sidebar-footer">
			<div class="runtime-heading"><span>{t("app.runtime")}</span><b>{STATIC ? "STATIC" : "LIVE"}</b></div>
			{#if !STATIC}
				<label class="api">
					<span class="backend-state"><i class="dot {online}"></i>{online === "up" ? t("app.backend.online") : online === "down" ? t("app.backend.offline") : t("app.backend.checking")}</span>
					<input aria-label={t("app.backend.address")} type="text" value={store.api} onchange={(e) => setApi((e.target as HTMLInputElement).value)} />
				</label>
			{:else}
				<span class="backend-state"><i class="dot up"></i>{t("app.static.mode")}</span>
			{/if}
			<p class="runtime-note">{t("app.runtimeNote")}</p>
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
		{#if tab === "research"}<ResearchTab view={researchView} designName={view.name} designId={view.designId} editSteps={editor.steps.length} staticMode={STATIC} {online} experimentId={researchExperiment} revisionId={researchRevision} onview={navigateResearch} onselect={selectResearch} ondesign={() => navigate("design")} onsim={() => navigate("sim")} />{:else if tab === "design"}<DesignTab onevolve={() => navigate("evolve")} onsim={() => navigate("sim")} />{:else if tab === "evolve"}<EvolveTab spec={view.linkage} onapply={applyEvolved} ondesign={() => navigate("design")} />{:else if tab === "fab"}<FabTab />{:else if tab === "sim"}<SimTab />{:else if tab === "beach"}<DigitalBeach />{:else}<LabTab />{/if}
	</main>
</div>
<CommandPalette bind:open={paletteOpen} onmessage={(m) => (editMessage = m)} />
<svelte:window onkeydown={keys} />

<style>
	.app-shell { min-height: 100dvh; display: grid; grid-template-columns: 224px minmax(0, 1fr); grid-template-rows: 68px minmax(0, 1fr); }
	.project-bar { grid-column: 1 / -1; display: grid; grid-template-columns: 224px minmax(0, 1fr) auto; align-items: center; background: var(--surface-raised); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 20; }
	.brand { height: 100%; display: flex; align-items: center; gap: 11px; padding: 0 18px; border-right: 1px solid var(--line); }
	.brand-mark { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); background: var(--surface); color: var(--accent); }
	.brand :global(svg) { width: 23px; height: 23px; flex: 0 0 auto; }
	.brand h1 { font-size: 15px; letter-spacing: -0.035em; white-space: nowrap; }
	.brand h1 span { color: var(--accent-strong); }
	.brand small { display: block; margin-top: 1px; font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase; }
	.project-context { min-width: 0; display: flex; align-items: center; gap: 12px; padding: 0 22px; }
	.context-symbol { width: 30px; height: 30px; display: grid; place-items: center; flex: 0 0 auto; color: var(--text-muted); border-right: 1px solid var(--line); padding-right: 10px; box-sizing: content-box; }
	.context-symbol :global(svg) { width: 17px; height: 17px; }
	.context-copy { min-width: 0; display: grid; gap: 1px; }
	.project-kicker { color: var(--text-muted); font-size: 9px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; white-space: nowrap; }
	.context-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
	.save-state, .research-context-state { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 11px; white-space: nowrap; }
	.save-state i, .research-context-state i { width: 6px; height: 6px; border-radius: 50%; background: var(--success); }
	.save-state.previewing i { background: var(--accent); }
	.research-context-state { padding: 3px 8px; border: 1px solid var(--line); border-radius: 999px; font-family: var(--font-mono); font-size: 9px; }
	.research-context-state i { background: transparent; border: 1px solid var(--text-muted); }
	.project-actions { display: flex; align-items: center; gap: 5px; padding-right: 16px; }
	.history-actions { display: flex; padding-right: 7px; margin-right: 3px; border-right: 1px solid var(--line); }
	.icon-btn { width: 36px; height: 36px; padding: 0; display: inline-grid; place-items: center; border: 1px solid transparent; border-radius: var(--radius-sm); background: transparent; color: var(--text-soft); cursor: pointer; }
	.icon-btn :global(svg), .command-button :global(svg) { width: 17px; height: 17px; }
	.icon-btn:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
	.icon-btn:disabled { opacity: 0.35; cursor: not-allowed; }
	.command-button { display: inline-flex; align-items: center; gap: 7px; }
	kbd { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
	.lang select { min-height: 36px; }
	.sidebar { grid-row: 2; position: sticky; top: 68px; align-self: start; height: calc(100dvh - 68px); display: flex; flex-direction: column; background: var(--surface); border-right: 1px solid var(--line); padding: 20px 12px 14px; }
	.sidebar nav { display: grid; gap: 18px; }
	.nav-group { display: grid; gap: 4px; }
	.nav-label { margin: 0; padding: 0 11px 6px; color: var(--text-faint); font-size: 9px; font-weight: 700; letter-spacing: 0.13em; text-transform: uppercase; }
	.nav-item { position: relative; width: 100%; min-height: 54px; display: flex; align-items: center; gap: 11px; padding: 8px 11px; border: 1px solid transparent; border-radius: var(--radius-sm); background: transparent; color: var(--text); text-align: left; cursor: pointer; transition: background-color 160ms ease-out, border-color 160ms ease-out, color 160ms ease-out; }
	.nav-item :global(svg) { width: 19px; height: 19px; color: var(--text-muted); flex: 0 0 auto; }
	.nav-item > span { display: grid; gap: 1px; }
	.nav-item b { font-size: 13px; font-weight: 600; }
	.nav-item small { font-size: 10px; color: var(--text-muted); }
	.nav-item:hover { background: var(--surface-hover); }
	.nav-item.active { background: var(--accent-soft); border-color: color-mix(in oklch, var(--accent) 16%, transparent); color: var(--accent-strong); }
	.nav-item.active :global(svg), .nav-item.active small { color: var(--accent-strong); }
	.nav-item.research.active { background: var(--info-soft); border-color: color-mix(in oklch, var(--info) 20%, transparent); color: var(--info); }
	.nav-item.research.active :global(svg), .nav-item.research.active small { color: var(--info); }
	.nav-indicator { position: absolute; right: -13px; width: 2px; height: 24px; border-radius: 2px; background: var(--accent); opacity: 0; }
	.research .nav-indicator { background: var(--info); }
	.nav-item.active .nav-indicator { opacity: 1; }
	.nav-item.secondary { min-height: 44px; }
	.secondary-group { padding-top: 14px; border-top: 1px solid var(--line); }
	.sidebar-footer { margin-top: auto; padding: 14px 8px 0; border-top: 1px solid var(--line); }
	.runtime-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; color: var(--text-faint); font-size: 9px; font-weight: 700; letter-spacing: 0.1em; }
	.runtime-heading b { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); }
	.api { width: 100%; gap: 8px; }
	.api input { width: 100%; font-family: var(--font-mono); font-size: 10px; }
	.backend-state { display: flex; align-items: center; gap: 7px; color: var(--text-soft); font-size: 11px; }
	.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex: 0 0 auto; box-shadow: 0 0 0 3px var(--neutral-soft); }
	.dot.up { background: var(--ok); box-shadow: 0 0 0 3px var(--success-soft); }
	.dot.down { background: var(--bad); box-shadow: 0 0 0 3px var(--danger-soft); }
	.runtime-note { margin: 12px 0 0; color: var(--text-faint); font-size: 10px; line-height: 1.55; }
	.workspace { min-width: 0; padding: 26px 28px 48px; outline: none; background: var(--workspace-bg); }
	.environment-notice { max-width: 1480px; margin: 0 auto 14px; }
	@media (max-width: 1120px) {
		.app-shell { grid-template-columns: 188px minmax(0, 1fr); }
		.project-bar { grid-template-columns: 188px minmax(0, 1fr) auto; }
		.brand { padding: 0 14px; }
		.project-context { padding: 0 14px; }
		.context-symbol, .save-state, .research-context-state, .command-button kbd { display: none; }
		.workspace { padding: 22px 20px 40px; }
	}
	@media (max-width: 820px) {
		.app-shell { display: block; }
		.project-bar { grid-template-columns: minmax(0, 1fr) auto; min-height: 64px; }
		.brand { border-right: 0; }
		.brand small { display: none; }
		.project-context { grid-row: 2; grid-column: 1 / -1; min-height: 42px; padding: 7px 14px; border-top: 1px solid var(--line); }
		.context-symbol, .save-state, .research-context-state { display: inline-flex; }
		.project-kicker { display: block; }
		.project-actions { padding-right: 10px; }
		.command-button span { display: none; }
		.sidebar { position: sticky; top: 106px; z-index: 15; width: 100%; height: auto; padding: 6px 10px; border-right: 0; border-bottom: 1px solid var(--line); }
		.sidebar nav { display: flex; gap: 4px; overflow-x: auto; scrollbar-width: thin; }
		.nav-group { display: contents; }
		.nav-label, .nav-item small, .nav-indicator { display: none; }
		.nav-item, .nav-item.secondary { width: auto; min-width: 78px; min-height: 44px; justify-content: center; padding: 7px 12px; }
		.nav-item > span { display: block; }
		.sidebar-footer { display: none; }
		.workspace { padding: 20px 16px 40px; }
	}
	@media (max-width: 480px) {
		.brand { padding-left: 12px; gap: 8px; }
		.brand-mark { width: 30px; height: 30px; }
		.brand h1 { font-size: 13px; }
		.brand :global(svg) { width: 20px; height: 20px; }
		.history-actions { padding-right: 2px; margin-right: 0; }
		.project-actions { gap: 1px; }
		.command-button { display: none; }
		.icon-btn { width: 40px; height: 40px; }
		.lang select { width: 62px; padding: 4px; }
		.project-context { gap: 8px; }
		.context-symbol, .research-context-state { display: none; }
		.save-state { margin-left: auto; font-size: 10px; }
		.sidebar { top: 106px; }
		.nav-item, .nav-item.secondary { min-width: 60px; padding: 7px 9px; }
		.nav-item.secondary { min-width: 84px; }
		.nav-item :global(svg) { display: none; }
		.nav-item b { white-space: nowrap; }
		.workspace { padding: 16px 12px 32px; }
	}
</style>
