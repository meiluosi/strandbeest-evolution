<script lang="ts">
import { diagText } from "./diag";
import { t } from "./i18n/index.svelte";
import type { Diagnosis } from "./replay-types";

/** "Why did it stop?": the rule-based explanation with the numbers it is based on. */
let { diagnosis }: { diagnosis: Diagnosis[] } = $props();
const SEV = {
	error: "diag.sev.error",
	warning: "diag.sev.warning",
	info: "diag.sev.info",
} as const;
</script>

<div class="diag">
	<h4>{t("diag.title")}</h4>
	{#each diagnosis as d}
		<div class="item {d.severity}">
			<b>{t(SEV[d.severity])}</b> {diagText(d)}
			<details>
				<summary>{t("diag.evidence")}</summary>
				<ul>{#each Object.entries(d.evidence) as [k, v]}<li><code>{k}</code> = {typeof v === "number" ? Number(v.toPrecision(4)) : v}</li>{/each}</ul>
			</details>
		</div>
	{/each}
</div>

<style>
	h4 { margin: 0 0 4px; }
	.item { border-left: 4px solid var(--line); padding: 4px 10px; margin: 6px 0; background: var(--bg); border-radius: 0 6px 6px 0; }
	.item.error { border-color: #d62828; }
	.item.warning { border-color: #c98a00; }
	.item.info { border-color: #2e8b57; }
	summary { cursor: pointer; color: var(--muted); font-size: 12px; }
	ul { margin: 4px 0 0 16px; padding: 0; font-size: 12px; }
</style>
