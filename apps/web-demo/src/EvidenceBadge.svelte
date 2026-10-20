<script lang="ts">
import { t } from "./i18n/index.svelte";

export type EvidenceLevel = "E0" | "E1" | "E2" | "E3";

export interface EvidenceInfo {
	level: EvidenceLevel;
	basis?: string[];
	downgraded?: boolean;
	downgrade_reason?: string;
	claims?: Record<
		string,
		{
			level: EvidenceLevel;
			basis?: string[];
			downgraded?: boolean;
			downgrade_reason?: string;
		}
	>;
}

let {
	evidence,
	compact = false,
}: {
	evidence?: EvidenceInfo | null;
	compact?: boolean;
} = $props();

const level = $derived<EvidenceLevel>(evidence?.level ?? "E0");
const downgraded = $derived<boolean>(evidence?.downgraded ?? false);
const basisText = $derived<string>(
	evidence?.basis && evidence.basis.length > 0 ? evidence.basis.join(", ") : "",
);

const descKey = $derived.by(() => {
	switch (level) {
		case "E1":
			return "evidence.e1.desc";
		case "E2":
			return "evidence.e2.desc";
		case "E3":
			return "evidence.e3.desc";
		default:
			return "evidence.e0.desc";
	}
});

const tooltip = $derived.by(() => {
	let text = t(descKey);
	if (downgraded && evidence?.downgrade_reason) {
		text += ` | ${t("evidence.downgradeReason", { reason: evidence.downgrade_reason })}`;
	} else if (basisText) {
		text += ` | ${t("evidence.basis", { basis: basisText })}`;
	}
	return text;
});
</script>

<span
	class="evidence-badge {level.toLowerCase()}"
	class:compact
	class:downgraded
	title={tooltip}
>
	<span class="lvl">{level}</span>
	{#if downgraded}
		<span class="downgrade-flag">{t("evidence.downgraded")}</span>
	{:else if !compact}
		<span class="lbl">{t(descKey)}</span>
	{/if}
</span>

<style>
	.evidence-badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11px;
		line-height: 1.2;
		padding: 2px 6px;
		border-radius: 4px;
		border: 1px solid var(--line);
		background: var(--bg);
		cursor: help;
		user-select: none;
	}
	.evidence-badge.compact {
		padding: 1px 4px;
	}
	.lvl {
		font-weight: 700;
		font-family: monospace;
	}
	.lbl {
		font-size: 10px;
		color: var(--muted);
	}
	.evidence-badge.e0 {
		border-color: var(--line);
		color: var(--muted);
	}
	.evidence-badge.e1 {
		border-color: rgba(47, 111, 209, 0.4);
		background: rgba(47, 111, 209, 0.08);
		color: var(--blue);
	}
	.evidence-badge.e2 {
		border-color: rgba(46, 139, 87, 0.4);
		background: rgba(46, 139, 87, 0.08);
		color: #2e8b57;
	}
	.evidence-badge.e3 {
		border-color: rgba(153, 50, 204, 0.4);
		background: rgba(153, 50, 204, 0.08);
		color: #9932cc;
	}
	.evidence-badge.downgraded {
		border-color: rgba(217, 98, 43, 0.5);
		color: var(--accent);
		background: rgba(217, 98, 43, 0.08);
	}
	.downgrade-flag {
		font-size: 10px;
		color: var(--accent);
	}
</style>
