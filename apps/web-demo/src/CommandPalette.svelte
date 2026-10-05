<script lang="ts">
import { lengthHandles, type Operation, type Problem } from "strandbeest-core";
import {
	currentDesign,
	edit,
	editor,
	newFromLinkage,
	redo,
	undo,
} from "./editor.svelte";
import { i18n, t } from "./i18n/index.svelte";
import {
	argsDef,
	type FieldSchema,
	fieldDoc,
	OP_TYPES,
	opLabel,
} from "./opdocs";
import { PRESETS } from "./presets";

let {
	open = $bindable(false),
	onmessage,
}: { open: boolean; onmessage: (text: string) => void } = $props();

interface Command {
	id: string;
	label: string;
	hint: string;
	enabled: boolean;
	run: () => void;
}

let query = $state("");
let cursor = $state(0);
let chosen = $state<string | null>(null);
let values = $state<Record<string, string>>({});
let reason = $state("");
let failure = $state<{ message: string; problems: Problem[] } | null>(null);
let input: HTMLInputElement | undefined = $state();

const commands = $derived.by((): Command[] => {
	void i18n.locale;
	const list: Command[] = [
		{
			id: "undo",
			label: t("palette.undo"),
			hint: "",
			enabled: editor.canUndo,
			run: () => report(undo()),
		},
		{
			id: "redo",
			label: t("palette.redo"),
			hint: "",
			enabled: editor.canRedo,
			run: () => report(redo()),
		},
	];
	for (const type of OP_TYPES)
		list.push({
			id: type,
			label: opLabel(type),
			hint: type,
			enabled: true,
			run: () => choose(type),
		});
	for (const p of PRESETS)
		list.push({
			id: `example:${p.id}`,
			label: t("palette.example", { name: p.id }),
			hint: "",
			enabled: true,
			run: () => {
				newFromLinkage(p.spec, p.id);
				close();
			},
		});
	return list;
});

const shown = $derived(
	commands.filter((c) => {
		const q = query.trim().toLowerCase();
		return (
			c.enabled &&
			(!q || `${c.label} ${c.hint} ${c.id}`.toLowerCase().includes(q))
		);
	}),
);

$effect(() => {
	if (open) {
		query = "";
		cursor = 0;
		chosen = null;
		failure = null;
		queueMicrotask(() => input?.focus());
	}
});
$effect(() => {
	void shown.length;
	if (cursor >= shown.length) cursor = Math.max(0, shown.length - 1);
});

function close() {
	open = false;
}

function report(r: { ok: boolean; message?: string }) {
	if (!r.ok) onmessage(r.message ?? "");
	close();
}

function prefill(type: string): Record<string, string> {
	const d = currentDesign();
	const lk = d.linkage;
	const handles = lengthHandles(lk);
	const first = handles.find((h) => h.group === "links") ?? handles[0];
	const points = ["G", "C", ...lk.joints.map((j) => j.id)];
	const free =
		["X", "Y", "Z", "W", "V", "U", "T", "S", "R", "Q"].find(
			(c) => !points.includes(c),
		) ?? "X2";
	const j = JSON.stringify;
	switch (type) {
		case "set_param":
			return {
				name: Object.keys(lk.params)[0] ?? "",
				value: String(Object.values(lk.params)[0] ?? ""),
			};
		case "set_length":
			return { key: first?.key ?? "", value: String(first?.value ?? "") };
		case "set_property":
			return { path: "/walker/legs", value: String(d.walker.legs) };
		case "add_dyad": {
			const last = lk.joints.at(-1)?.id ?? "C";
			return {
				id: free,
				centers: j(["C", last]),
				radii: j(["r1", "r2"]),
				side: "-1",
				params: j({ r1: 30, r2: 25 }),
				foot: "true",
			};
		}
		case "remove_joint":
			return {
				id: lk.joints.at(-1)?.id ?? "",
				foot: lk.joints.at(-2)?.id ?? "C",
				drop_params: "true",
			};
		case "array_legs":
			return { legs: String(d.walker.legs) };
		case "scale":
			return { factor: "1.1", keep_physical: "false" };
		case "set_material":
			return { material: d.manufacturing.material };
		default:
			return {};
	}
}

function choose(type: string) {
	chosen = type;
	values = prefill(type);
	reason = "";
	failure = null;
}

const form = $derived(chosen ? argsDef(chosen) : null);

function kindOf(
	f: FieldSchema,
): "enum" | "boolean" | "number" | "text" | "json" {
	if (f.enum) return "enum";
	const ty = Array.isArray(f.type) ? f.type[0] : f.type;
	if (ty === "boolean") return "boolean";
	if (ty === "number" || ty === "integer") return "number";
	if (ty === "string") return "text";
	return "json";
}

function parse(f: FieldSchema, raw: string): unknown {
	switch (kindOf(f)) {
		case "enum":
			return (f.enum as unknown[]).find((v) => String(v) === raw) ?? raw;
		case "boolean":
			return raw === "true";
		case "number":
			return Number(raw);
		case "text":
			return raw;
		default:
			try {
				return JSON.parse(raw);
			} catch {
				return raw;
			}
	}
}

function submit() {
	if (!chosen || !form) return;
	const args: Record<string, unknown> = {};
	try {
		for (const [name, f] of form.fields) {
			const raw = values[name] ?? "";
			if (raw === "" && !form.required.includes(name)) continue;
			args[name] = parse(f, raw);
		}
	} catch (e) {
		failure = { message: String(e), problems: [] };
		return;
	}
	const r = edit(chosen as Operation["type"], args, reason);
	if (r.ok) close();
	else failure = { message: r.message ?? "", problems: r.problems ?? [] };
}

function key(e: KeyboardEvent) {
	if (e.key === "Escape") {
		e.preventDefault();
		if (chosen) chosen = null;
		else close();
	} else if (!chosen && e.key === "ArrowDown") {
		e.preventDefault();
		cursor = Math.min(shown.length - 1, cursor + 1);
	} else if (!chosen && e.key === "ArrowUp") {
		e.preventDefault();
		cursor = Math.max(0, cursor - 1);
	} else if (!chosen && e.key === "Enter") {
		e.preventDefault();
		shown[cursor]?.run();
	}
}
</script>

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="backdrop" onclick={close}>
		<div class="palette" role="dialog" tabindex="-1" aria-modal="true" aria-label={t("palette.title")} onclick={(e) => e.stopPropagation()} onkeydown={key}>
			{#if !chosen}
				<input bind:this={input} bind:value={query} placeholder={t("palette.placeholder")} aria-label={t("palette.placeholder")} />
				<ul role="listbox">
					{#each shown as c, i (c.id)}
						<li role="option" aria-selected={i === cursor}>
							<button class:active={i === cursor} onclick={() => c.run()} onmousemove={() => (cursor = i)}>
								<span>{c.label}</span>{#if c.hint}<small>{c.hint}</small>{/if}
							</button>
						</li>
					{:else}
						<li class="muted empty">{t("palette.empty")}</li>
					{/each}
				</ul>
			{:else if form}
				<div class="head">
					<button class="btn small" onclick={() => (chosen = null)}>{t("palette.back")}</button>
					<b>{opLabel(chosen)}</b> <small>{form.title}</small>
				</div>
				<form onsubmit={(e) => { e.preventDefault(); submit(); }}>
					{#each form.fields as [name, f] (name)}
						<label>
							<span class="n">{name}{form.required.includes(name) ? " *" : ""}{#if f["x-unit"]}<small> ({f["x-unit"]})</small>{/if}</span>
							{#if kindOf(f) === "enum"}
								<select bind:value={values[name]}>
									{#each f.enum ?? [] as v}<option value={String(v)}>{String(v)}</option>{/each}
								</select>
							{:else if kindOf(f) === "boolean"}
								<select bind:value={values[name]}><option value="true">true</option><option value="false">false</option></select>
							{:else if kindOf(f) === "number"}
								<input type="number" step="any" bind:value={values[name]} />
							{:else if kindOf(f) === "text"}
								<input type="text" bind:value={values[name]} />
							{:else}
								<textarea rows="2" bind:value={values[name]}></textarea>
							{/if}
							<small class="muted">{fieldDoc(f)}</small>
						</label>
					{/each}
					<label>
						<span class="n">{t("palette.reason")}</span>
						<input type="text" bind:value={reason} placeholder={t("palette.reasonHint")} />
					</label>
					{#if failure}
						<div class="notice error">
							{failure.message}
							{#if failure.problems.length}<ul>{#each failure.problems as p}<li><code>{p.code}</code> {p.message}</li>{/each}</ul>{/if}
						</div>
					{/if}
					<div class="row"><button class="btn primary" type="submit">{t("palette.apply")}</button></div>
				</form>
			{/if}
		</div>
	</div>
{/if}

<style>
	.backdrop { position: fixed; inset: 0; background: #0006; z-index: 50; display: flex; justify-content: center; align-items: flex-start; padding-top: 12vh; }
	.palette { background: var(--card); border: 1px solid var(--line); border-radius: 12px; width: min(560px, calc(100vw - 32px)); max-height: 70vh; overflow: auto; padding: 12px; box-shadow: 0 12px 40px #0004; display: flex; flex-direction: column; gap: 8px; }
	input, select, textarea { width: 100%; box-sizing: border-box; }
	ul { list-style: none; margin: 0; padding: 0; }
	li button { display: flex; justify-content: space-between; width: 100%; text-align: left; background: transparent; border: none; padding: 8px 10px; border-radius: 8px; color: var(--ink); cursor: pointer; font: inherit; }
	li button.active { background: var(--bg); }
	li small { color: var(--muted); }
	.empty { padding: 8px 10px; }
	.head { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
	form { display: flex; flex-direction: column; gap: 8px; }
	label { display: flex; flex-direction: column; gap: 2px; }
	.n { font-weight: 600; }
	.notice ul { margin: 4px 0 0 16px; padding: 0; list-style: disc; }
</style>
