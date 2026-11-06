<script lang="ts">
import Icon from "./Icon.svelte";
import { t } from "./i18n/index.svelte";
import StateBadge from "./StateBadge.svelte";

let {
	name,
	designId,
	legs,
	editSteps,
	previewing = false,
}: {
	name: string;
	designId: string;
	legs: number;
	editSteps: number;
	previewing?: boolean;
} = $props();
</script>

<section class="design-context-bar" aria-label={t("design.contextAria")}>
	<div class="design-identity">
		<span class="design-symbol"><Icon name="design" /></span>
		<div><small>{t("research.localDesign")}</small><strong>{name}</strong></div>
	</div>
	<dl>
		<div><dt>{t("research.designId")}</dt><dd title={designId}>{designId}</dd></div>
		<div><dt>{t("design.legs")}</dt><dd>{legs}</dd></div>
		<div><dt>{t("research.editHistory")}</dt><dd>{t("research.editSteps", { n: editSteps })}</dd></div>
	</dl>
	<StateBadge
		label={previewing ? t("app.previewing") : t("app.localHistory", { n: editSteps })}
		tone={previewing ? "accent" : "info"}
		live={previewing}
	/>
</section>

<style>
	.design-context-bar { display: grid; grid-template-columns: minmax(180px, 1fr) auto auto; align-items: center; gap: 22px; margin-bottom: 16px; padding: 10px 14px; border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface-inset); }
	.design-identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
	.design-symbol { display: grid; place-items: center; width: 32px; height: 32px; flex: 0 0 auto; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--surface); color: var(--accent); }
	.design-symbol :global(svg) { width: 16px; height: 16px; }
	.design-identity > div { display: grid; min-width: 0; gap: 1px; }
	.design-identity small { color: var(--text-faint); font-size: 9px; }
	.design-identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
	dl { display: flex; align-items: center; gap: 0; margin: 0; }
	dl > div { min-width: 94px; padding: 0 16px; border-left: 1px solid var(--line); }
	dl > div:first-child { min-width: 150px; }
	dt { color: var(--text-faint); font-size: 8px; letter-spacing: 0.04em; text-transform: uppercase; }
	dd { margin: 2px 0 0; overflow: hidden; color: var(--text-soft); font-family: var(--font-mono); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
	@media (max-width: 1120px) {
		.design-context-bar { grid-template-columns: minmax(160px, 1fr) auto; gap: 12px; }
		.design-context-bar > :global(.state-badge) { grid-column: 1 / -1; grid-row: 2; justify-self: start; }
	}
	@media (max-width: 600px) {
		.design-context-bar { grid-template-columns: minmax(0, 1fr); gap: 12px; padding: 12px; }
		dl { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(54px, 0.6fr) minmax(0, 1fr); }
		dl > div, dl > div:first-child { min-width: 0; padding: 0 10px; }
		dl > div:first-child { padding-left: 0; border-left: 0; }
		.design-context-bar > :global(.state-badge) { grid-column: auto; grid-row: auto; }
	}
</style>
