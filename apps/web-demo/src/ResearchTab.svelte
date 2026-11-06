<script lang="ts" module>
export type ResearchView = "protocol" | "runs" | "evidence";
</script>

<script lang="ts">
import Icon from "./Icon.svelte";
import { t } from "./i18n/index.svelte";

let {
	view,
	designName,
	designId,
	editSteps,
	staticMode,
	online,
	onview,
	ondesign,
	onsim,
}: {
	view: ResearchView;
	designName: string;
	designId: string;
	editSteps: number;
	staticMode: boolean;
	online: "unknown" | "up" | "down";
	onview: (view: ResearchView) => void;
	ondesign: () => void;
	onsim: () => void;
} = $props();

const views = [
	["protocol", "research.protocol", "research.protocolShort", "protocol"],
	["runs", "research.runs", "research.runsShort", "runs"],
	["evidence", "research.evidence", "research.evidenceShort", "evidence"],
] as const;

const emptyTitle = $derived(
	view === "protocol"
		? "research.emptyProtocolTitle"
		: view === "runs"
			? "research.emptyRunsTitle"
			: "research.emptyEvidenceTitle",
);
const emptyDescription = $derived(
	view === "protocol"
		? "research.emptyProtocolDescription"
		: view === "runs"
			? "research.emptyRunsDescription"
			: "research.emptyEvidenceDescription",
);
const modeLabel = $derived(
	staticMode
		? "research.staticContext"
		: online === "up"
			? "research.liveContext"
			: online === "down"
				? "research.offlineContext"
				: "research.checkingContext",
);
</script>

<section class="research-workspace">
	<header class="workspace-header research-header">
		<div>
			<p class="eyebrow">{t("research.eyebrow")}</p>
			<h2>{t("research.title")}</h2>
			<p>{t("research.description")}</p>
		</div>
		<div class="phase-stamp" aria-label={t("research.phaseAria")}>
			<span>M1</span>
			<div><b>{t("research.phase")}</b><small>{t("research.phaseNote")}</small></div>
		</div>
	</header>

	<div class="research-viewbar">
		<div class="research-tabs" role="tablist" aria-label={t("research.views")}>
			{#each views as [id, label, short, icon], index}
				<button
					id={`research-tab-${id}`}
					role="tab"
					aria-selected={view === id}
					aria-controls="research-panel"
					class:active={view === id}
					onclick={() => onview(id)}
				>
					<span class="view-index">0{index + 1}</span>
					<Icon name={icon} />
					<span><b>{t(label)}</b><small>{t(short)}</small></span>
				</button>
			{/each}
		</div>
		<span class="research-mode"><i class:offline={!staticMode && online === "down"}></i>{t(modeLabel)}</span>
	</div>

	<div
		class="research-panel"
		id="research-panel"
		role="tabpanel"
		aria-labelledby={`research-tab-${view}`}
	>
		<div class="research-empty">
			<div class="empty-visual" aria-hidden="true">
				<span class="orbit orbit-a"></span>
				<span class="orbit orbit-b"></span>
				<span class="empty-symbol"><Icon name={view === "protocol" ? "protocol" : view === "runs" ? "runs" : "evidence"} /></span>
				<i class="node node-a"></i><i class="node node-b"></i><i class="node node-c"></i>
			</div>
			<p class="eyebrow">{t("research.noExperiment")}</p>
			<h3>{t(emptyTitle)}</h3>
			<p class="empty-description">{t(emptyDescription)}</p>
			<div class="empty-actions">
				<button class="btn primary" onclick={ondesign}><Icon name="design" />{t("research.openDesign")}</button>
				<button class="btn" onclick={onsim}><Icon name="sim" />{t("research.openSimulation")}</button>
			</div>
			<p class="empty-note"><Icon name="evidence" />{t("research.emptyNote")}</p>
		</div>

		<aside class="domain-context" aria-label={t("research.domainContext")}>
			<div class="context-heading">
				<span>{t("research.domainContext")}</span>
				<i>{t("research.available")}</i>
			</div>
			<div class="domain-object">
				<span class="object-icon"><Icon name="design" /></span>
				<div><small>{t("research.localDesign")}</small><strong>{designName}</strong></div>
			</div>
			<dl>
				<div><dt>{t("research.designId")}</dt><dd title={designId}>{designId}</dd></div>
				<div><dt>{t("research.editHistory")}</dt><dd>{t("research.editSteps", { n: editSteps })}</dd></div>
				<div><dt>{t("research.experimentRevision")}</dt><dd class="unbound">{t("research.notBound")}</dd></div>
			</dl>
			<p>{t("research.domainHint")}</p>
		</aside>
	</div>

	<section class="research-journey" aria-labelledby="journey-title">
		<div class="journey-heading">
			<div><p class="eyebrow">{t("research.journeyEyebrow")}</p><h3 id="journey-title">{t("research.journeyTitle")}</h3></div>
			<span>{t("research.journeyScope")}</span>
		</div>
		<ol>
			<li><span>01</span><div><b>{t("research.journeyProtocol")}</b><small>{t("research.journeyProtocolHint")}</small></div></li>
			<li><span>02</span><div><b>{t("research.journeyData")}</b><small>{t("research.journeyDataHint")}</small></div></li>
			<li><span>03</span><div><b>{t("research.journeyEvaluation")}</b><small>{t("research.journeyEvaluationHint")}</small></div></li>
			<li><span>04</span><div><b>{t("research.journeyEvidence")}</b><small>{t("research.journeyEvidenceHint")}</small></div></li>
		</ol>
	</section>
</section>

<style>
	.research-workspace { max-width: 1480px; margin: 0 auto; }
	.research-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
	.research-header > div:first-child { max-width: 760px; }
	.eyebrow { margin: 0 0 5px; color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; font-weight: 600; letter-spacing: 0.13em; }
	.phase-stamp { display: flex; align-items: center; gap: 11px; padding: 9px 12px; border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface); }
	.phase-stamp > span { display: grid; place-items: center; width: 36px; height: 36px; border-radius: var(--radius-sm); background: var(--info-soft); color: var(--info); font-family: var(--font-mono); font-size: 13px; font-weight: 700; }
	.phase-stamp div { display: grid; gap: 1px; }
	.phase-stamp b { font-size: 11px; }
	.phase-stamp small { font-size: 9px; white-space: nowrap; }
	.research-viewbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--line); }
	.research-tabs { display: flex; gap: 4px; }
	.research-tabs button { position: relative; display: flex; align-items: center; gap: 10px; min-width: 180px; padding: 12px 16px 13px; border: 0; background: transparent; color: var(--text-muted); text-align: left; cursor: pointer; }
	.research-tabs button::after { content: ""; position: absolute; left: 12px; right: 12px; bottom: -1px; height: 2px; background: var(--info); transform: scaleX(0); transition: transform 160ms ease-out; }
	.research-tabs button.active::after { transform: scaleX(1); }
	.research-tabs button.active { color: var(--text); }
	.research-tabs button:hover { color: var(--text); background: var(--surface-hover); }
	.research-tabs button :global(svg) { width: 18px; height: 18px; }
	.research-tabs button > span:last-child { display: grid; gap: 1px; }
	.research-tabs b { font-size: 12px; font-weight: 600; }
	.research-tabs small { font-size: 9px; }
	.view-index { color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; }
	.research-mode { display: inline-flex; align-items: center; gap: 7px; color: var(--text-muted); font-size: 10px; white-space: nowrap; }
	.research-mode i { width: 6px; height: 6px; border-radius: 50%; background: var(--info); }
	.research-mode i.offline { background: var(--danger); }
	.research-panel { display: grid; grid-template-columns: minmax(0, 1fr) 310px; min-height: 390px; border: 1px solid var(--line); border-top: 0; background: var(--surface); }
	.research-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; min-width: 0; padding: 40px 32px 32px; text-align: center; }
	.empty-visual { position: relative; width: 116px; height: 94px; margin-bottom: 18px; color: var(--info); }
	.empty-symbol { position: absolute; left: 38px; top: 25px; width: 42px; height: 42px; display: grid; place-items: center; border: 1px solid var(--line-strong); border-radius: 50%; background: var(--surface-raised); }
	.empty-symbol :global(svg) { width: 21px; height: 21px; }
	.orbit { position: absolute; border: 1px solid var(--line); border-radius: 50%; transform: rotate(-18deg); }
	.orbit-a { inset: 7px 0; }
	.orbit-b { inset: 20px 16px; transform: rotate(24deg); }
	.node { position: absolute; width: 5px; height: 5px; border-radius: 50%; background: var(--accent); }
	.node-a { left: 13px; top: 24px; }
	.node-b { right: 14px; bottom: 22px; background: var(--info); }
	.node-c { left: 53px; top: 6px; background: var(--text-faint); }
	.research-empty h3 { margin: 0; font-size: 21px; font-weight: 600; letter-spacing: -0.025em; }
	.empty-description { max-width: 580px; margin: 10px auto 0; color: var(--text-soft); font-size: 13px; line-height: 1.75; }
	.empty-actions { display: flex; gap: 8px; margin-top: 22px; }
	.empty-actions .btn { display: inline-flex; align-items: center; gap: 7px; }
	.empty-actions :global(svg) { width: 15px; height: 15px; }
	.empty-note { display: flex; align-items: center; gap: 7px; margin: 22px 0 0; color: var(--text-faint); font-size: 10px; }
	.empty-note :global(svg) { width: 13px; height: 13px; }
	.domain-context { padding: 22px; border-left: 1px solid var(--line); background: var(--surface-inset); }
	.context-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; color: var(--text-faint); font-size: 9px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
	.context-heading i { padding: 2px 6px; border: 1px solid var(--line); border-radius: 999px; color: var(--success); font-style: normal; font-size: 8px; letter-spacing: 0; }
	.domain-object { display: flex; align-items: center; gap: 10px; margin-top: 22px; }
	.object-icon { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--line); border-radius: var(--radius-sm); color: var(--accent); background: var(--surface); }
	.object-icon :global(svg) { width: 17px; height: 17px; }
	.domain-object > div { min-width: 0; display: grid; gap: 2px; }
	.domain-object small { font-size: 9px; }
	.domain-object strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
	.domain-context dl { margin: 20px 0 0; }
	.domain-context dl > div { display: grid; grid-template-columns: 86px minmax(0, 1fr); gap: 10px; padding: 10px 0; border-top: 1px solid var(--line); font-size: 10px; }
	.domain-context dt { color: var(--text-muted); }
	.domain-context dd { min-width: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono); text-align: right; }
	.domain-context dd.unbound { color: var(--text-faint); font-family: var(--font-ui); }
	.domain-context > p { margin: 18px 0 0; color: var(--text-faint); font-size: 10px; line-height: 1.65; }
	.research-journey { margin-top: 22px; padding: 20px 22px 22px; border: 1px solid var(--line); background: var(--surface-inset); }
	.journey-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; }
	.journey-heading h3 { margin: 0; font-size: 13px; }
	.journey-heading > span { color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; }
	.research-journey ol { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin: 20px 0 0; padding: 0; list-style: none; }
	.research-journey li { position: relative; display: flex; gap: 10px; min-width: 0; padding: 0 18px; border-left: 1px solid var(--line); }
	.research-journey li:first-child { padding-left: 0; border-left: 0; }
	.research-journey li > span { color: var(--accent); font-family: var(--font-mono); font-size: 10px; }
	.research-journey li > div { display: grid; gap: 3px; }
	.research-journey b { font-size: 11px; font-weight: 600; }
	.research-journey small { font-size: 9px; line-height: 1.5; }
	@media (max-width: 1120px) {
		.research-tabs button { min-width: 160px; padding-inline: 12px; }
		.research-panel { grid-template-columns: minmax(0, 1fr) 270px; }
		.domain-context { padding: 18px; }
		.research-journey ol { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 0; }
		.research-journey li:nth-child(3) { padding-left: 0; border-left: 0; }
	}
	@media (max-width: 820px) {
		.research-viewbar { align-items: stretch; flex-direction: column; gap: 0; }
		.research-tabs { width: 100%; }
		.research-tabs button { flex: 1; min-width: 0; justify-content: center; }
		.research-mode { align-self: flex-end; margin: 8px 0; }
		.research-panel { grid-template-columns: minmax(0, 1fr); }
		.domain-context { border-left: 0; border-top: 1px solid var(--line); }
		.domain-context dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
		.domain-context dl > div { display: block; }
		.domain-context dd { margin-top: 4px; text-align: left; }
	}
	@media (max-width: 480px) {
		.research-header { align-items: flex-start; }
		.phase-stamp { padding: 6px; }
		.phase-stamp > span { width: 30px; height: 30px; }
		.phase-stamp div { display: none; }
		.research-tabs button { gap: 6px; padding: 10px 6px; }
		.research-tabs button :global(svg), .view-index, .research-tabs small { display: none; }
		.research-tabs b { font-size: 11px; }
		.research-empty { padding: 32px 18px 26px; }
		.research-empty h3 { font-size: 18px; }
		.empty-actions { width: 100%; flex-direction: column; }
		.empty-actions .btn { justify-content: center; }
		.empty-note { align-items: flex-start; text-align: left; }
		.domain-context dl { grid-template-columns: minmax(0, 1fr); gap: 0; }
		.domain-context dl > div { display: grid; grid-template-columns: 82px minmax(0, 1fr); }
		.domain-context dd { text-align: right; }
		.research-journey { padding: 18px; }
		.journey-heading { align-items: flex-start; flex-direction: column; gap: 5px; }
		.research-journey ol { grid-template-columns: minmax(0, 1fr); gap: 16px; }
		.research-journey li, .research-journey li:nth-child(3) { padding: 0; border-left: 0; }
	}
</style>
