<script lang="ts">
import { canCreateSnapshot, defaultAssignments, groupRuns } from "./harness";
import type { DatasetSnapshot, RunSummary, Split } from "./harness-api";
import Icon from "./Icon.svelte";
import { t } from "./i18n/index.svelte";

let {
	runs,
	snapshot,
	busy,
	oncreate,
	onvalidate,
}: {
	runs: RunSummary[];
	snapshot?: DatasetSnapshot;
	busy: boolean;
	oncreate: (input: {
		runIds: string[];
		channels: string[];
		assignments: { group_id: string; split: Split }[];
	}) => void;
	onvalidate: () => void;
} = $props();

let creating = $state(false);
let selected = $state<Set<string>>(new Set());
let channels = $state("t, psi, torque");
let assignments = $state<Record<string, Split>>({});
const groups = $derived(groupRuns(runs, selected));
const assignmentList = $derived(
	defaultAssignments(groups.map((group) => group.groupId)).map(
		(assignment) => ({
			...assignment,
			split: assignments[assignment.group_id] ?? assignment.split,
		}),
	),
);
const valid = $derived(
	canCreateSnapshot(
		groups.map((group) => group.groupId),
		assignmentList,
	),
);

function toggle(runId: string) {
	const next = new Set(selected);
	if (next.has(runId)) next.delete(runId);
	else next.add(runId);
	selected = next;
}
</script>

<section class="snapshot-section" aria-labelledby="snapshot-title">
	<div class="section-heading"><div><p class="eyebrow">DATASET</p><h3 id="snapshot-title">{t("harness.snapshotTitle")}</h3><p>{t("harness.snapshotDescription")}</p></div>{#if snapshot}<span class="snapshot-count">{snapshot.total_samples}<small>{t("harness.samples")}</small></span>{/if}</div>
	{#if snapshot}
		<div class="snapshot-identity"><div><span>{t("harness.snapshotId")}</span><code>{snapshot.id}</code></div><div><span>{t("harness.digest")}</span><code title={snapshot.digest}>{snapshot.digest}</code></div><button class="btn" type="button" disabled={busy} onclick={onvalidate}><Icon name="evidence" />{t("harness.validateSnapshot")}</button></div>
		<div class="split-grid">
			{#each snapshot.split.assignments as assignment}<div class="split-card" data-split={assignment.split}><span>{t(`harness.split.${assignment.split}`)}</span><strong>{assignment.group_id}</strong><small>{snapshot.sources.filter((source) => source.group_id === assignment.group_id).length} {t("harness.episodes")}</small></div>{/each}
		</div>
		<!-- Keyboard scrolling is required for the wide source table. -->
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<div class="table-wrapper" tabindex="0" role="region" aria-label={t("harness.sourceEpisodes")}>
			<table><caption class="sr">{t("harness.sourceEpisodes")}</caption><thead><tr><th scope="col">{t("harness.episode")}</th><th scope="col">{t("harness.group")}</th><th scope="col">{t("harness.channels")}</th><th scope="col">{t("harness.samples")}</th><th scope="col">{t("harness.arraysDigest")}</th></tr></thead><tbody>{#each snapshot.sources as source}<tr><th scope="row">{source.episode_id}</th><td>{source.group_id}</td><td>{source.channels.join(", ")}</td><td>{source.sample_count}</td><td><code title={source.arrays_sha256}>{source.arrays_sha256}</code></td></tr>{/each}</tbody></table>
		</div>
		<p class="snapshot-note"><Icon name="evidence" />{t("harness.snapshotNote")}</p>
	{/if}
	<div class="snapshot-create">
		<button class="btn {snapshot ? '' : 'primary'}" type="button" aria-expanded={creating} aria-controls="snapshot-form" onclick={() => (creating = !creating)}><Icon name="dataset" />{t("harness.createSnapshot")}</button>
		{#if creating}
			<form id="snapshot-form" action="/api/harness/v1/dataset-snapshots" method="post" onsubmit={(event) => { event.preventDefault(); oncreate({ runIds: [...selected], channels: channels.split(",").map((channel) => channel.trim()).filter(Boolean), assignments: assignmentList }); }}>
				<fieldset>
					<legend>{t("harness.freezeRealRuns")}</legend>
					<p class="form-hint">{t("harness.snapshotFormHint")}</p>
					{#if runs.length}<div class="run-picker">{#each runs as run}<label class:chosen={selected.has(run.id)}><input type="checkbox" name="run" value={run.id} checked={selected.has(run.id)} onchange={() => toggle(run.id)}><span><b>{run.design_name}</b><code>{run.id}</code></span>{#if run.stalled}<i>{t("harness.stalled")}</i>{/if}</label>{/each}</div>{:else}<p class="no-runs">{t("harness.noRuns")}</p>{/if}
					<div class="field"><label for="snapshot-channels">{t("harness.channels")}</label><span id="snapshot-channels-hint" class="hint">{t("harness.channelsHint")}</span><input id="snapshot-channels" name="channels" bind:value={channels} aria-describedby="snapshot-channels-hint" required spellcheck="false" autocapitalize="off" autocorrect="off"></div>
					{#if groups.length}<div class="group-splits"><h4>{t("harness.groupSplits")}</h4>{#each groups as group}<div><span><b>{group.name}</b><small>{group.runIds.length} {t("harness.episodes")}</small></span><label><span class="sr">{t("harness.splitFor", { name: group.name })}</span><select name={`split-${group.groupId}`} value={assignments[group.groupId] ?? assignmentList.find((assignment) => assignment.group_id === group.groupId)?.split} onchange={(event) => (assignments[group.groupId] = (event.target as HTMLSelectElement).value as Split)}><option value="train">{t("harness.split.train")}</option><option value="development">{t("harness.split.development")}</option><option value="test">{t("harness.split.test")}</option></select></label></div>{/each}</div>{/if}
					{#if selected.size > 0 && !valid}<p class="validation-hint" role="alert">{t("harness.splitRequirement")}</p>{/if}
					<button class="btn primary" type="submit" disabled={busy}>{busy ? t("harness.submitting") : t("harness.freezeSnapshot")}</button>
				</fieldset>
			</form>
		{/if}
	</div>
</section>

<style>
	.snapshot-section { min-width: 0; padding: 20px 22px; border: 1px solid var(--line); background: var(--surface); }
	.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
	.section-heading h3 { margin: 0; font-size: 15px; }
	.section-heading p:last-child { max-width: 680px; margin: 6px 0 0; color: var(--text-muted); font-size: 11px; line-height: 1.6; }
	.eyebrow { margin: 0 0 5px; color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; letter-spacing: .12em; }
	.snapshot-count { display: grid; color: var(--accent-strong); font-family: var(--font-mono); font-size: 22px; text-align: right; }
	.snapshot-count small { color: var(--text-faint); font-size: 8px; }
	.snapshot-identity { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr) auto; align-items: center; gap: 12px; margin-top: 16px; padding: 12px; background: var(--surface-inset); }
	.snapshot-identity > div { display: grid; min-width: 0; gap: 4px; }
	.snapshot-identity span { color: var(--text-muted); font-size: 9px; }
	.snapshot-identity code { overflow: hidden; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
	.snapshot-identity .btn { display: inline-flex; align-items: center; gap: 6px; }
	.snapshot-identity :global(svg) { width: 14px; height: 14px; }
	.split-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; margin-top: 12px; }
	.split-card { display: grid; min-width: 0; gap: 5px; padding: 12px; border-top: 2px solid var(--info); background: var(--info-soft); }
	.split-card[data-split="test"] { border-color: var(--accent); background: var(--accent-soft); }
	.split-card[data-split="development"] { border-color: var(--text-faint); background: var(--surface-inset); }
	.split-card span { font-size: 10px; font-weight: 650; }
	.split-card strong { overflow: hidden; font-family: var(--font-mono); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
	.split-card small { color: var(--text-muted); font-size: 9px; }
	.table-wrapper { max-inline-size: 100%; margin-top: 14px; overflow: auto; }
	table { width: 100%; border-collapse: collapse; font-size: 9px; text-align: left; }
	thead { position: sticky; inset-block-start: 0; }
	th, td { max-width: 250px; padding: 10px; overflow: hidden; border-bottom: 1px solid var(--line); text-overflow: ellipsis; white-space: nowrap; }
	thead th { background: var(--surface-inset); color: var(--text-muted); }
	tbody th { background: var(--surface); font-family: var(--font-mono); font-weight: 400; }
	td code { color: var(--text-faint); }
	.snapshot-note { display: flex; align-items: center; gap: 7px; margin: 12px 0 0; color: var(--text-faint); font-size: 10px; }
	.snapshot-note :global(svg) { width: 13px; height: 13px; }
	.snapshot-create { margin-top: 16px; }
	.snapshot-create > .btn { display: inline-flex; align-items: center; gap: 7px; }
	.snapshot-create :global(svg) { width: 14px; height: 14px; }
	form { margin-top: 14px; padding: 16px; border: 1px solid var(--line-strong); background: var(--surface-inset); }
	fieldset { display: grid; gap: 14px; margin: 0; padding: 0; border: 0; }
	legend { padding: 0; font-size: 13px; font-weight: 650; }
	.form-hint { margin: 0; color: var(--text-muted); font-size: 11px; }
	.run-picker { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; max-height: 260px; overflow: auto; }
	.run-picker > label { display: flex; align-items: center; gap: 9px; min-width: 0; min-height: 48px; padding: 8px 10px; border: 1px solid var(--line); background: var(--surface); cursor: pointer; }
	.run-picker > label.chosen { border-color: var(--accent); }
	.run-picker input { width: 16px; height: 16px; flex: 0 0 auto; accent-color: var(--accent); }
	.run-picker label > span { display: grid; min-width: 0; gap: 3px; }
	.run-picker b { font-size: 10px; }
	.run-picker code { overflow: hidden; color: var(--text-faint); font-size: 8px; text-overflow: ellipsis; }
	.run-picker i { margin-left: auto; color: var(--danger); font-size: 8px; font-style: normal; }
	.field { display: grid; gap: 6px; }
	.field label { font-size: 11px; font-weight: 600; }
	.field input { min-height: 42px; font-size: 1rem; }
	.hint { color: var(--text-muted); font-size: 10px; }
	.no-runs { padding: 14px; border: 1px dashed var(--line-strong); color: var(--text-muted); font-size: 11px; }
	.group-splits h4 { margin: 0 0 8px; font-size: 11px; }
	.group-splits > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-top: 1px solid var(--line); }
	.group-splits div > span { display: grid; gap: 3px; }
	.group-splits b { font-size: 10px; }
	.group-splits small { color: var(--text-muted); font-size: 9px; }
	.group-splits select { min-height: 38px; }
	.validation-hint { margin: 0; color: var(--danger); font-size: 11px; }
	.snapshot-create form .btn { justify-self: start; }
	@media (max-width: 700px) {
		.snapshot-identity { grid-template-columns: minmax(0, 1fr); }
		.snapshot-identity .btn { justify-self: start; }
		.split-grid { grid-template-columns: minmax(0, 1fr); }
		.run-picker { grid-template-columns: minmax(0, 1fr); }
	}
	@media (pointer: coarse) { .field input, .group-splits select { min-height: 52px; } }
</style>
