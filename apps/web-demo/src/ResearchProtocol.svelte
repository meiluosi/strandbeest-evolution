<script lang="ts">
import { revisionDifferences } from "./harness";
import type {
	AssetKind,
	DatasetSnapshot,
	Experiment,
	ExperimentRevision,
	LineageEdge,
} from "./harness-api";
import Icon from "./Icon.svelte";
import { t } from "./i18n/index.svelte";

const kindKeys: Record<AssetKind, string> = {
	design: "harness.kind.design",
	run: "harness.kind.run",
	measurement: "harness.kind.measurement",
	profile: "harness.kind.profile",
	dataset_snapshot: "harness.kind.dataset_snapshot",
};
const roleKeys: Record<string, string> = {
	baseline: "harness.role.baseline",
	learned: "harness.role.learned",
	control: "harness.role.control",
};
const diffKeys: Record<string, string> = {
	question: "harness.diff.question",
	design: "harness.diff.design",
	sourceRuns: "harness.diff.sourceRuns",
	snapshot: "harness.diff.snapshot",
	scenario: "harness.scenario",
	conditions: "harness.diff.conditions",
	trials: "harness.diff.trials",
	evaluation: "harness.diff.evaluation",
	budget: "harness.diff.budget",
};

let {
	experiment,
	revision,
	base,
	snapshot,
	lineage,
	busy,
	message,
	onvalidate,
	onderive,
}: {
	experiment: Experiment;
	revision: ExperimentRevision;
	base?: ExperimentRevision;
	snapshot?: DatasetSnapshot;
	lineage: LineageEdge[];
	busy: boolean;
	message: string;
	onvalidate: () => void;
	onderive: (input: {
		question: string;
		seed: number;
		purpose: "initial" | "independent_replication";
		maxTrials: number;
		maxCompute: number;
		attachSnapshot: boolean;
	}) => void;
} = $props();

let deriving = $state(false);
let question = $state("");
let seed = $state(1);
let purpose = $state<"initial" | "independent_replication">(
	"independent_replication",
);
let maxTrials = $state(1);
let maxCompute = $state(60);
let attachSnapshot = $state(false);
const differences = $derived(revisionDifferences(revision, base));
const refs = $derived([
	revision.inputs.design,
	...revision.inputs.source_runs,
	...(revision.inputs.dataset_snapshot
		? [revision.inputs.dataset_snapshot]
		: []),
]);

$effect(() => {
	revision.id;
	question = revision.question;
	seed = Math.max(...revision.trials.map((trial) => trial.seed)) + 1;
	maxTrials = revision.budget.max_trials;
	maxCompute = revision.budget.max_compute_seconds;
	deriving = false;
	attachSnapshot = false;
});

function conditionLabel(id: string): string {
	return (
		revision.conditions.find((condition) => condition.id === id)?.label ?? id
	);
}
</script>

<div class="protocol-content">
	<section class="protocol-overview" aria-labelledby="protocol-title">
		<div class="section-heading">
			<div><p class="eyebrow">{t("harness.immutableRevision")}</p><h3 id="protocol-title">{experiment.title}</h3><p>{revision.question}</p></div>
			<span class="revision-stamp">R{revision.revision}<small>{revision.id}</small></span>
		</div>
		<div class="protocol-actions">
			<button class="btn" type="button" disabled={busy} onclick={onvalidate}><Icon name="evidence" />{t("harness.validateProtocol")}</button>
			<button class="btn primary" type="button" disabled={busy} aria-expanded={deriving} aria-controls="derive-form" onclick={() => (deriving = !deriving)}><Icon name="branch" />{t("harness.deriveRevision")}</button>
		</div>
		{#if message}<p class="form-status" role="status">{message}</p>{/if}
		{#if deriving}
			<form id="derive-form" class="derive-form" action="/api/harness/v1/experiments" method="post" onsubmit={(event) => { event.preventDefault(); onderive({ question, seed, purpose, maxTrials, maxCompute, attachSnapshot }); }}>
				<fieldset>
					<legend>{t("harness.newRevision")}</legend>
					<p class="form-hint">{t("harness.deriveHint")}</p>
					<div class="field wide"><label for="revision-question">{t("harness.question")}</label><textarea id="revision-question" name="question" bind:value={question} required minlength="1"></textarea></div>
					<div class="field"><label for="revision-seed">{t("harness.seed")}</label><input id="revision-seed" name="seed" type="number" bind:value={seed} required></div>
					<div class="field"><label for="revision-purpose">{t("harness.trialPurpose")}</label><select id="revision-purpose" name="purpose" bind:value={purpose}><option value="independent_replication">{t("harness.independentReplication")}</option><option value="initial">{t("harness.initialTrial")}</option></select></div>
					<div class="field"><label for="revision-max-trials">{t("harness.maxTrials")}</label><input id="revision-max-trials" name="max_trials" type="number" min="1" bind:value={maxTrials} required></div>
					<div class="field"><label for="revision-max-compute">{t("harness.maxCompute")}</label><input id="revision-max-compute" name="max_compute_seconds" type="number" min="1" bind:value={maxCompute} required></div>
					{#if snapshot}<label class="check-field"><input type="checkbox" name="attach_snapshot" bind:checked={attachSnapshot}>{t("harness.attachSnapshot")}</label>{/if}
					<button class="btn primary" type="submit" disabled={busy}>{busy ? t("harness.submitting") : t("harness.freezeRevision")}</button>
				</fieldset>
			</form>
		{/if}
		{#if base}
			<details class="revision-diff" open={differences.length > 0}>
				<summary>{t("harness.revisionDiff", { n: differences.length })}</summary>
				{#if differences.length}<div class="diff-list">{#each differences as diff}<div><b>{t(diffKeys[diff.key] ?? "harness.diff.question")}</b><del>{diff.before}</del><ins>{diff.after}</ins></div>{/each}</div>{:else}<p>{t("harness.noScientificDiff")}</p>{/if}
			</details>
		{/if}
	</section>

	<section class="protocol-section" aria-labelledby="frozen-title">
		<div class="section-title"><div><p class="eyebrow">INPUTS</p><h3 id="frozen-title">{t("harness.frozenInputs")}</h3></div><span>{t("harness.contentAddressed")}</span></div>
		<div class="reference-grid">
			{#each refs as ref}<div class="reference-item"><span>{t(kindKeys[ref.kind])}</span><strong title={ref.id}>{ref.id}</strong><code title={ref.digest}>{ref.digest}</code></div>{/each}
			{#if revision.inputs.scenario}<div class="reference-item"><span>{t("harness.scenario")}</span><strong>{t("harness.frozenDocument")}</strong><code>{revision.inputs.scenario.digest}</code></div>{/if}
		</div>
	</section>

	<section class="protocol-section" aria-labelledby="conditions-title">
		<div class="section-title"><div><p class="eyebrow">PROTOCOL</p><h3 id="conditions-title">{t("harness.conditionsTrials")}</h3></div><span>{revision.conditions.length} / {revision.trials.length}</span></div>
		<!-- Keyboard scrolling is required for the responsive table region. -->
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<div class="table-wrapper" tabindex="0" role="region" aria-labelledby="conditions-title">
			<table style:--label-role={t("harness.role")} style:--label-trial={t("harness.trial")} style:--label-seed={t("harness.seed")} style:--label-purpose={t("harness.trialPurpose")}><caption class="sr">{t("harness.conditionsTrials")}</caption><thead><tr><th scope="col">{t("harness.condition")}</th><th scope="col">{t("harness.role")}</th><th scope="col">{t("harness.trial")}</th><th scope="col">{t("harness.seed")}</th><th scope="col">{t("harness.trialPurpose")}</th></tr></thead><tbody>
				{#each revision.trials as trial}<tr><th scope="row">{conditionLabel(trial.condition_id)}<small>{trial.condition_id}</small></th><td>{t(roleKeys[revision.conditions.find((condition) => condition.id === trial.condition_id)?.role ?? "baseline"] ?? "harness.role.baseline")}</td><td>{trial.key}<small>{trial.id}</small></td><td class="numeric">{trial.seed}</td><td>{t(trial.purpose === "initial" ? "harness.initialTrial" : "harness.independentReplication")}</td></tr>{/each}
			</tbody></table>
		</div>
	</section>

	<div class="protocol-lower">
		<section class="protocol-section compact"><p class="eyebrow">EVALUATION</p><h3>{revision.evaluation_suite.key} · R{revision.evaluation_suite.revision}</h3><ul class="metric-list">{#each revision.evaluation_suite.metrics as metric}<li>{metric}</li>{/each}</ul></section>
		<section class="protocol-section compact"><p class="eyebrow">LIMITS</p><h3>{t("harness.budgetPermission")}</h3><dl class="limits"><div><dt>{t("harness.maxTrials")}</dt><dd>{revision.budget.max_trials}</dd></div><div><dt>{t("harness.maxCompute")}</dt><dd>{revision.budget.max_compute_seconds} s</dd></div><div><dt>{t("harness.permission")}</dt><dd>{t("harness.manualOnly")}</dd></div></dl></section>
	</div>

	<section class="protocol-section" aria-labelledby="lineage-title">
		<div class="section-title"><div><p class="eyebrow">PROVENANCE</p><h3 id="lineage-title">{t("harness.lineage")}</h3></div><span>{t("harness.directEdges", { n: lineage.length })}</span></div>
		{#if lineage.length}<ol class="lineage-list">{#each lineage as edge}<li><span>{edge.relation}</span><div><b>{edge.parent_kind} · {edge.parent_id}</b><i>→</i><strong>{edge.child_kind} · {edge.child_id}</strong></div></li>{/each}</ol>{:else}<p class="muted">{t("harness.noLineage")}</p>{/if}
	</section>
</div>

<style>
	.protocol-content { display: grid; gap: 16px; }
	.protocol-overview, .protocol-section { min-width: 0; padding: 20px 22px; border: 1px solid var(--line); background: var(--surface); }
	.section-heading, .section-title, .protocol-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
	.section-heading > div { min-width: 0; }
	.section-heading h3, .section-title h3, .compact h3 { margin: 0; font-size: 15px; }
	.section-heading p:last-child { margin: 7px 0 0; color: var(--text-soft); font-size: 12px; line-height: 1.6; }
	.eyebrow { margin: 0 0 5px; color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; letter-spacing: .12em; }
	.revision-stamp { display: grid; flex: 0 0 auto; gap: 4px; max-width: 260px; color: var(--accent-strong); font-family: var(--font-mono); font-size: 18px; text-align: right; }
	.revision-stamp small { overflow: hidden; color: var(--text-faint); font-size: 8px; text-overflow: ellipsis; }
	.protocol-actions { justify-content: flex-start; margin-top: 18px; }
	.protocol-actions .btn, .derive-form .btn { display: inline-flex; align-items: center; gap: 7px; }
	.protocol-actions :global(svg) { width: 14px; height: 14px; }
	.form-status { padding: 9px 12px; border-left: 2px solid var(--success); background: var(--success-soft); font-size: 11px; }
	.derive-form { margin-top: 18px; padding: 16px; border: 1px solid var(--line-strong); background: var(--surface-inset); }
	.derive-form fieldset { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px 16px; margin: 0; padding: 0; border: 0; }
	.derive-form legend { padding: 0; font-size: 13px; font-weight: 650; }
	.form-hint, .derive-form .wide, .check-field, .derive-form .btn { grid-column: 1 / -1; }
	.form-hint { margin: 0; color: var(--text-muted); font-size: 11px; }
	.field { display: grid; align-content: start; gap: 6px; min-width: 0; }
	.field label { color: var(--text-soft); font-size: 11px; font-weight: 600; }
	.field input, .field textarea, .field select { width: 100%; min-height: 42px; box-sizing: border-box; font-size: 1rem; }
	.field textarea { min-height: 76px; resize: vertical; }
	.check-field { display: flex; align-items: center; gap: 8px; min-height: 32px; font-size: 11px; }
	.check-field input { width: 17px; height: 17px; accent-color: var(--accent); }
	.revision-diff { margin-top: 16px; border-top: 1px solid var(--line); }
	.revision-diff summary { padding-top: 13px; color: var(--text-soft); cursor: pointer; font-size: 11px; }
	.diff-list { display: grid; gap: 8px; margin-top: 12px; }
	.diff-list > div { display: grid; grid-template-columns: 130px minmax(0, 1fr) minmax(0, 1fr); gap: 10px; font-family: var(--font-mono); font-size: 9px; }
	.diff-list b { font-family: var(--font-ui); }
	del, ins { min-width: 0; overflow-wrap: anywhere; text-decoration: none; }
	del { color: var(--danger); } ins { color: var(--success); }
	.section-title > span { color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; }
	.reference-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin-top: 15px; }
	.reference-item { display: grid; min-width: 0; gap: 5px; padding: 11px 12px; border: 1px solid var(--line); background: var(--surface-inset); }
	.reference-item span { color: var(--text-muted); font-size: 9px; }
	.reference-item strong, .reference-item code { overflow: hidden; font-family: var(--font-mono); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
	.reference-item code { color: var(--text-faint); }
	.table-wrapper { max-inline-size: 100%; margin-top: 14px; overflow: auto; container-type: inline-size; }
	table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 10px; text-align: left; }
	thead { position: sticky; inset-block-start: 0; z-index: 1; }
	th, td { padding: 11px 12px; border-bottom: 1px solid var(--line); }
	thead th { background: var(--surface-inset); color: var(--text-muted); font-size: 9px; font-weight: 600; }
	tbody th { position: sticky; inset-inline-start: 0; background: var(--surface); font-weight: 600; }
	tbody small { display: block; margin-top: 3px; color: var(--text-faint); font-family: var(--font-mono); font-size: 8px; font-weight: 400; }
	.numeric { font-family: var(--font-mono); }
	.protocol-lower { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
	.metric-list { display: flex; flex-wrap: wrap; gap: 7px; margin: 14px 0 0; padding: 0; list-style: none; }
	.metric-list li { padding: 5px 8px; border: 1px solid var(--line); color: var(--text-soft); font-family: var(--font-mono); font-size: 9px; }
	.limits { margin: 10px 0 0; }
	.limits div { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--line); font-size: 10px; }
	.limits dd { margin: 0; text-align: right; }
	.lineage-list { display: grid; gap: 7px; margin: 14px 0 0; padding: 0; list-style: none; }
	.lineage-list li { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 12px; padding: 9px 11px; background: var(--surface-inset); }
	.lineage-list li > span { color: var(--accent-strong); font-family: var(--font-mono); font-size: 9px; }
	.lineage-list div { display: flex; min-width: 0; gap: 8px; font-family: var(--font-mono); font-size: 9px; }
	.lineage-list b, .lineage-list strong { min-width: 0; overflow: hidden; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
	.lineage-list i { color: var(--text-faint); font-style: normal; }
	.muted { color: var(--text-muted); font-size: 11px; }
	@container (width < 620px) {
		table, thead, tbody, tr, th, td { display: block; }
		thead { display: none; }
		tr { padding: 10px 12px; border-bottom: 1px solid var(--line); }
		tbody th { position: static; padding: 0 0 8px; }
		td { display: grid; grid-template-columns: 110px minmax(0, 1fr); padding: 4px 0; border: 0; overflow-wrap: anywhere; }
		td:nth-child(2)::before { content: var(--label-role); }
		td:nth-child(3)::before { content: var(--label-trial); }
		td:nth-child(4)::before { content: var(--label-seed); }
		td:nth-child(5)::before { content: var(--label-purpose); }
	}
	@media (max-width: 820px) {
		.protocol-lower { grid-template-columns: minmax(0, 1fr); }
		.diff-list > div { grid-template-columns: 100px minmax(0, 1fr); }
		.diff-list ins { grid-column: 2; }
		.lineage-list li { grid-template-columns: minmax(0, 1fr); }
	}
	@media (max-width: 520px) {
		.protocol-overview, .protocol-section { padding: 16px; }
		.section-heading { align-items: flex-start; }
		.revision-stamp { max-width: 90px; }
		.protocol-actions { align-items: stretch; flex-direction: column; }
		.derive-form fieldset, .reference-grid { grid-template-columns: minmax(0, 1fr); }
		.lineage-list div { flex-direction: column; }
		.lineage-list b, .lineage-list strong { white-space: normal; overflow-wrap: anywhere; }
	}
	@media (pointer: coarse) { .field input, .field select { min-height: 52px; } }
</style>
