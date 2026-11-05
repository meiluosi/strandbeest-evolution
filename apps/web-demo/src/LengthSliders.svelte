<script lang="ts">
import {
	type LengthHandle,
	type LinkageSpec,
	lengthHandles,
} from "strandbeest-core";
import { t } from "./i18n/index.svelte";

let {
	spec,
	onpreview,
	oncommit,
}: {
	spec: LinkageSpec;
	onpreview: (key: string, value: number) => void;
	oncommit: (key: string, value: number) => void;
} = $props();

const handles = $derived(lengthHandles(spec));
const GROUPS = [
	{ id: "crank", title: "sliders.crank", hint: "sliders.crank.hint" },
	{ id: "links", title: "sliders.links", hint: "sliders.links.hint" },
] as const;
const groups = $derived(
	GROUPS.map((g) => ({
		...g,
		items: handles.filter((h) => h.group === g.id),
	})),
);

const CRANK_ROLES: Record<string, string> = {
	"crank.x": "sliders.crankX",
	"crank.y": "sliders.crankY",
	"crank.length": "sliders.crankLength",
};

function role(h: LengthHandle): string {
	return h.uses
		.map((u) => (u in CRANK_ROLES ? t(CRANK_ROLES[u] as string) : u))
		.join(", ");
}

function value(e: Event): number | null {
	const v = Number.parseFloat((e.target as HTMLInputElement).value);
	return Number.isFinite(v) ? v : null;
}
const preview = (key: string, e: Event) => {
	const v = value(e);
	if (v !== null) onpreview(key, v);
};
const commit = (key: string, e: Event) => {
	const v = value(e);
	if (v !== null) oncommit(key, v);
};
</script>

<div class="parameter-groups">
	{#each groups as g}
		{#if g.items.length}
			<section class="parameter-group">
				<h4>{t(g.title)}<small>{t(g.hint)}</small></h4>
				{#each g.items as h (h.key)}
					{@const id = `length-${h.key.replace(/[^a-zA-Z0-9_-]/g, "-")}`}
					<div class="parameter">
						<div class="parameter-label">
							<label for={id} title={role(h)}>{h.label}</label>
							<small>{role(h)}</small>
						</div>
						<div class="parameter-inputs">
							<input id={id} aria-label={t("sliders.rangeFor", { name: h.label })} type="range" min={h.range[0]} max={h.range[1]} step="0.1" value={h.value} oninput={(e) => preview(h.key, e)} onchange={(e) => commit(h.key, e)} />
							<input aria-label={t("sliders.valueFor", { name: h.label })} title={t("sliders.range", { lo: h.range[0], hi: h.range[1] })} type="number" min={h.range[0]} max={h.range[1]} step="0.1" value={h.value} oninput={(e) => preview(h.key, e)} onchange={(e) => commit(h.key, e)} />
						</div>
					</div>
				{/each}
			</section>
		{/if}
	{/each}
</div>

<style>
	.parameter-groups { padding: 4px 16px 0; }
	.parameter-group + .parameter-group { margin-top: 15px; padding-top: 13px; border-top: 1px solid var(--line); }
	h4 { margin: 0 0 8px; font-size: 12px; }
	h4 small { display: block; margin-top: 2px; font-weight: 400; font-size: 11px; }
	.parameter { padding: 7px 0; }
	.parameter-label { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 2px; }
	.parameter-label label { color: var(--text); font-family: var(--font-mono); font-size: 12px; font-weight: 600; }
	.parameter-label small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
	.parameter-inputs { display: grid; grid-template-columns: minmax(0, 1fr) 66px; align-items: center; gap: 9px; }
	input[type="number"] { width: 66px; padding: 4px 5px; font-size: 11px; }
	@media (max-width: 480px) {
		.parameter-groups { padding-left: 12px; padding-right: 12px; }
		.parameter { padding: 9px 0; }
		input[type="range"] { min-height: 32px; }
		input[type="number"] { min-height: 40px; }
	}
</style>
