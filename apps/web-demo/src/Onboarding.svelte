<script lang="ts">
import { t } from "./i18n/index.svelte";

const KEY = "strandbeest-onboarding-dismissed";
let { onevolve, onsim }: { onevolve: () => void; onsim: () => void } = $props();

function seen(): boolean {
	try {
		return localStorage.getItem(KEY) === "1";
	} catch {
		return false;
	}
}
let hidden = $state(seen());
function dismiss() {
	hidden = true;
	try {
		localStorage.setItem(KEY, "1");
	} catch {
		/* storage unavailable: it will show again next visit */
	}
}
</script>

{#if !hidden}
	<aside class="card hello" aria-label={t("onboarding.title")}>
		<div class="row center" style="justify-content: space-between; margin: 0">
			<h2 style="margin: 0">{t("onboarding.title")}</h2>
			<button class="btn small" onclick={dismiss}>{t("onboarding.dismiss")}</button>
		</div>
		<p class="muted">{t("onboarding.intro")}</p>
		<ol>
			<li>{t("onboarding.step1")}</li>
			<li>{t("onboarding.step2")} <button class="btn small" onclick={onevolve}>{t("onboarding.goEvolve")}</button></li>
			<li>{t("onboarding.step3")} <button class="btn small" onclick={onsim}>{t("onboarding.goSim")}</button></li>
		</ol>
	</aside>
{/if}

<style>
	.hello { border-left: 4px solid var(--accent); }
	ol { margin: 6px 0 0; padding-left: 20px; display: grid; gap: 6px; }
</style>
