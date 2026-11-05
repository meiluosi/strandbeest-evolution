<script lang="ts">
import type { Design, LinkageSpec } from "strandbeest-core";
import Evolver from "./Evolver.svelte";
import { openDocument } from "./editor.svelte";
import { t } from "./i18n/index.svelte";
import MapElitesGrid from "./MapElitesGrid.svelte";

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
	<header class="workspace-header">
		<div>
			<span class="eyebrow">{t("evolve.workspaceEyebrow")}</span>
			<h2>{t("evolve.workspaceTitle")}</h2>
			<p>{t("evolve.workspaceDescription")}</p>
		</div>
		<button class="btn" onclick={ondesign}>{t("evolve.backToDesign")}</button>
	</header>

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
	.workspace-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
	.eyebrow { display: block; color: var(--accent-strong); font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: 0.13em; }
	.workspace-header h2 { margin-top: 4px; font-size: clamp(24px, 2.3vw, 32px); letter-spacing: -0.04em; }
	.workspace-header p { margin-top: 5px; color: var(--text-soft); }
	.atlas-workspace { min-width: 0; margin-top: 24px; padding: 20px; border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface); box-shadow: var(--shadow-sm); }
	.atlas-separator { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 16px; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
	.atlas-separator > span { color: var(--accent-strong); font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: 0.12em; white-space: nowrap; }
	.atlas-separator p { margin: 0; color: var(--text-muted); font-size: 11px; text-align: right; }
	@media (max-width: 600px) {
		.workspace-header { align-items: flex-start; flex-direction: column; gap: 14px; margin-bottom: 16px; }
		.workspace-header .btn { width: 100%; }
		.atlas-workspace { padding: 14px; }
		.atlas-separator { align-items: flex-start; flex-direction: column; gap: 6px; }
		.atlas-separator p { text-align: left; }
	}
</style>
