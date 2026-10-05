<script lang="ts">
import type { Operation } from "strandbeest-core";
import { download } from "./api";
import { editor, exportLog, redo, undo } from "./editor.svelte";
import { i18n, t } from "./i18n/index.svelte";
import { opLabel } from "./opdocs";

let { onmessage }: { onmessage: (text: string) => void } = $props();

const ACTORS = {
	human: "actor.human",
	algorithm: "actor.algorithm",
	agent: "actor.agent",
} as const;
const steps = $derived([...editor.steps].reverse());
const count = $derived(editor.steps.reduce((n, s) => n + s.length, 0));

function brief(o: Operation): string {
	const a = o.args as Record<string, unknown>;
	const parts = Object.entries(a).map(
		([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`,
	);
	return parts.join(", ");
}

function time(o: Operation): string {
	const d = new Date(o.time);
	return Number.isNaN(d.getTime())
		? ""
		: d.toLocaleTimeString(i18n.locale === "zh" ? "zh-CN" : "en");
}

function run(fn: () => { ok: boolean; message?: string }) {
	const r = fn();
	if (!r.ok) onmessage(r.message ?? "");
}
</script>

<div class="history">
	<div class="row center">
		<button class="btn small" disabled={!editor.canUndo} onclick={() => run(undo)}>{t("history.undo")}</button>
		<button class="btn small" disabled={!editor.canRedo} onclick={() => run(redo)}>{t("history.redo")}</button>
		<span class="muted">{t("history.count", { n: count })}</span>
		<button class="btn small" onclick={() => download("oplog.json", JSON.stringify(exportLog(), null, 2))}>{t("history.download")}</button>
	</div>
	{#if editor.restoredPartly}
		<p class="notice error">{t("history.restoredPartly", { kept: editor.restoredPartly })}</p>
	{/if}
	{#if steps.length === 0}
		<p class="muted">{t("history.empty")}</p>
	{:else}
		<ol class="log">
			{#each steps as step, i (steps.length - i)}
				<li>
					{#each step as o (o.id)}
						<div class="entry">
							<b>{opLabel(o.type)}</b>
							<span class="actor {o.actor.kind}">{t(ACTORS[o.actor.kind])}{o.actor.id && o.actor.id !== "web" ? ` · ${o.actor.id}` : ""}</span>
							<small>{time(o)}</small>
							<code title={JSON.stringify(o.args)}>{brief(o)}</code>
							{#if o.reason}<em>{o.reason}</em>{/if}
						</div>
					{/each}
				</li>
			{/each}
		</ol>
	{/if}
</div>

<style>
	.history { display: flex; flex-direction: column; gap: 8px; }
	.log { margin: 0; padding: 0; list-style: none; max-height: 240px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }
	.log li { padding: 6px 10px; border-bottom: 1px solid var(--line); }
	.log li:last-child { border-bottom: none; }
	.entry { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; font-size: 13px; }
	code { background: var(--bg); padding: 1px 5px; border-radius: 4px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.actor { font-size: 11px; padding: 0 6px; border-radius: 8px; background: var(--bg); color: var(--muted); }
	.actor.agent { color: var(--accent); }
	.actor.algorithm { color: var(--blue); }
	em { color: var(--muted); }
</style>
