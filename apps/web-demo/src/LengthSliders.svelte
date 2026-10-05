<script lang="ts">
import {
	type LengthHandle,
	type LinkageSpec,
	lengthHandles,
	withLength,
} from "strandbeest-core";
import { t } from "./i18n/index.svelte";

let { spec = $bindable() }: { spec: LinkageSpec } = $props();

const handles = $derived(lengthHandles(spec));
const GROUPS = [
	{ id: "crank", title: "sliders.crank", hint: "sliders.crank.hint" },
	{ id: "links", title: "sliders.links", hint: "sliders.links.hint" },
] as const;
const groups = $derived(
	GROUPS.map((g) => ({ ...g, items: handles.filter((h) => h.group === g.id) })),
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

function set(key: string, e: Event) {
	const v = Number.parseFloat((e.target as HTMLInputElement).value);
	if (Number.isFinite(v)) spec = withLength(spec, key, v);
}
</script>

<div class="stack">
	{#each groups as g}
		{#if g.items.length}
			<div>
				<h3>{t(g.title)} <small>{t(g.hint)}</small></h3>
				{#each g.items as h (h.key)}
					<div class="s">
						<span class="n" title={role(h)}>{h.label}<small> {role(h)}</small></span>
						<input type="range" min={h.range[0]} max={h.range[1]} step="0.1" value={h.value} oninput={(e) => set(h.key, e)} />
						<input type="number" min={h.range[0]} max={h.range[1]} step="0.1" value={h.value} oninput={(e) => set(h.key, e)} />
					</div>
				{/each}
			</div>
		{/if}
	{/each}
</div>


<style>
	.s { display: grid; grid-template-columns: 112px 1fr 64px; gap: 8px; align-items: center; margin: 3px 0; }
	.n { font-weight: 600; white-space: nowrap; }
	.n small { margin-left: 6px; font-weight: 400; }
	input[type="number"] { width: 64px; padding: 2px 5px; }
</style>
