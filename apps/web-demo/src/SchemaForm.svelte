<script lang="ts">
import { i18n, t } from "./i18n/index.svelte";
import {
	type ExtractOptions,
	extractFields,
	getByPath,
	type SchemaField,
} from "./schema-form";

let {
	schema,
	value,
	sections,
	include,
	exclude,
	groups,
	showGroups = true,
	onchange,
}: {
	schema: Record<string, unknown>;
	value: Record<string, unknown>;
	sections?: string[];
	include?: string[];
	exclude?: string[];
	groups?: string[];
	showGroups?: boolean;
	onchange: (field: SchemaField, nextValue: unknown) => void;
} = $props();

const fields = $derived(
	extractFields(schema, {
		sections,
		include,
		exclude,
		groups,
	} satisfies ExtractOptions),
);

const grouped = $derived.by(() => {
	const map = new Map<string, SchemaField[]>();
	for (const f of fields) {
		const g = f.group ?? "group.root";
		const list = map.get(g) ?? [];
		list.push(f);
		map.set(g, list);
	}
	return Array.from(map.entries());
});

function readFieldValue(f: SchemaField): unknown {
	const v = getByPath(value, f.path);
	return v !== undefined ? v : f.defaultValue;
}

function handleInput(f: SchemaField, e: Event) {
	const target = e.target as HTMLInputElement | HTMLSelectElement;
	if (f.kind === "boolean") {
		onchange(f, (target as HTMLInputElement).checked);
		return;
	}
	if (f.kind === "enum") {
		const raw = target.value;
		const matched = f.enumValues?.find((ev) => String(ev) === raw);
		onchange(f, matched !== undefined ? matched : raw);
		return;
	}
	if (f.kind === "integer") {
		const n = Number.parseInt(target.value, 10);
		if (Number.isFinite(n)) onchange(f, n);
		return;
	}
	if (f.kind === "number") {
		if (f.nullable && target.value.trim() === "") {
			onchange(f, null);
			return;
		}
		const n = Number.parseFloat(target.value);
		if (Number.isFinite(n)) onchange(f, n);
		return;
	}
	onchange(f, target.value);
}
</script>

<div class="schema-form">
	{#each grouped as [groupKey, groupFields]}
		<div class="schema-group">
			{#if showGroups && grouped.length > 1}
				<div class="group-title">{t(groupKey)}</div>
			{/if}
			<div class="schema-grid">
				{#each groupFields as f (f.path)}
					{@const currentVal = readFieldValue(f)}
					{@const labelText = i18n.locale === "zh" ? f.doc.zh : f.doc.en}
					<div class="schema-field" title={f.path}>
						<div class="field-header">
							<span class="field-label">{labelText}</span>
							{#if f.unit}
								<span class="badge unit">{f.unit}</span>
							{/if}
							{#if f.assumption}
								<span
									class="badge assumption"
									title={f.source
										? t("schemaForm.sourceHint", { source: f.source })
										: t("schemaForm.assumptionHint")}
								>
									{t("schemaForm.assumption")}
								</span>
							{/if}
							{#if f.calibratable}
								<span
									class="badge calibratable"
									title={t("schemaForm.calibratableHint")}
								>
									{t("schemaForm.calibratable")}
								</span>
							{/if}
						</div>
						<div class="field-control">
							{#if f.kind === "enum" && f.enumValues}
								<select
									value={String(currentVal ?? "")}
									onchange={(e) => handleInput(f, e)}
								>
									{#each f.enumValues as ev}
										<option value={String(ev)}>{String(ev)}</option>
									{/each}
								</select>
							{:else if f.kind === "boolean"}
								<input
									type="checkbox"
									checked={Boolean(currentVal)}
									onchange={(e) => handleInput(f, e)}
								/>
							{:else if f.kind === "number" || f.kind === "integer"}
								<input
									type="number"
									min={f.min}
									max={f.max}
									step={f.step}
									value={currentVal === null || currentVal === undefined
										? ""
										: String(currentVal)}
									onchange={(e) => handleInput(f, e)}
								/>
							{:else}
								<input
									type="text"
									value={String(currentVal ?? "")}
									onchange={(e) => handleInput(f, e)}
								/>
							{/if}
							{#if f.range}
								<small class="range-hint">
									{t("schemaForm.range", {
										lo: f.range[0],
										hi: f.range[1],
									})}
								</small>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/each}
</div>

<style>
	.schema-form {
		display: flex;
		flex-direction: column;
		gap: 10px;
		margin: 6px 0;
	}
	.group-title {
		font-size: 12px;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin-bottom: 4px;
	}
	.schema-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
		gap: 8px 12px;
	}
	.schema-field {
		display: flex;
		flex-direction: column;
		gap: 3px;
		padding: 6px 8px;
		border: 1px solid var(--line);
		border-radius: 6px;
		background: var(--bg);
	}
	.field-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
		font-size: 12px;
	}
	.field-label {
		font-weight: 500;
	}
	.badge {
		font-size: 10px;
		padding: 1px 5px;
		border-radius: 4px;
		line-height: 1.3;
	}
	.badge.unit {
		background: var(--line);
		color: var(--fg);
		font-family: monospace;
	}
	.badge.assumption {
		background: rgba(217, 98, 43, 0.14);
		color: var(--accent);
		border: 1px solid rgba(217, 98, 43, 0.35);
		cursor: help;
	}
	.badge.calibratable {
		background: rgba(47, 111, 209, 0.14);
		color: var(--blue);
		border: 1px solid rgba(47, 111, 209, 0.35);
		cursor: help;
	}
	.field-control {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.field-control input[type="number"],
	.field-control input[type="text"],
	.field-control select {
		width: 100%;
		max-width: 150px;
	}
	.range-hint {
		color: var(--muted);
		font-size: 11px;
		white-space: nowrap;
	}
</style>
