<script lang="ts">
import type { Design, LinkageSpec } from "strandbeest-core";
import DesignContextBar from "./DesignContextBar.svelte";
import Evolver from "./Evolver.svelte";
import { editor, openDocument } from "./editor.svelte";
import Icon from "./Icon.svelte";
import { t } from "./i18n/index.svelte";
import MapElitesGrid from "./MapElitesGrid.svelte";
import { view } from "./store.svelte";
import WorkspaceHeader from "./WorkspaceHeader.svelte";

let {
	spec,
	onapply,
	ondesign,
}: {
	spec: LinkageSpec;
	onapply: (spec: LinkageSpec) => void;
	ondesign: () => void;
} = $props();

function loadAtlasDesign(design: Design) {
	openDocument(structuredClone(design));
	ondesign();
}
</script>

<div class="evolution-workspace">
	<WorkspaceHeader
		eyebrow={t("evolve.workspaceEyebrow")}
		title={t("evolve.workspaceTitle")}
		description={t("evolve.workspaceDescription")}
	>
		{#snippet actions()}
			<button class="btn" onclick={ondesign}><Icon name="design" />{t("evolve.backToDesign")}</button>
		{/snippet}
	</WorkspaceHeader>

	<DesignContextBar
		name={view.name}
		designId={view.designId}
		legs={view.legs}
		editSteps={editor.steps.length}
	/>

	<Evolver {spec} {onapply} />

	<section class="atlas-workspace" aria-label={t("map_elites.title")}>
		<div class="atlas-separator">
			<span>{t("evolve.atlasEyebrow")}</span>
			<p>{t("evolve.atlasNote")}</p>
		</div>
		<MapElitesGrid onload={loadAtlasDesign} />
	</section>
</div>

<style>
	.evolution-workspace { max-width: 1480px; margin: 0 auto; }
	.atlas-workspace { min-width: 0; margin-top: 24px; padding: 20px; border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface-inset); }
	.atlas-separator { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 16px; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
	.atlas-separator > span { color: var(--text-faint); font-family: var(--font-mono); font-size: 9px; font-weight: 600; letter-spacing: 0.12em; white-space: nowrap; }
	.atlas-separator p { max-width: 760px; margin: 0; color: var(--text-muted); font-size: 11px; line-height: 1.55; text-align: right; }
	@media (max-width: 600px) {
		.atlas-workspace { padding: 14px; }
		.atlas-separator { align-items: flex-start; flex-direction: column; gap: 6px; }
		.atlas-separator p { text-align: left; }
	}
</style>
