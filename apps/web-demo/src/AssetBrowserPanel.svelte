<script lang="ts">
import {
	buildGenealogyTree,
	type Design,
	diffDesigns,
	flattenGenealogyTree,
} from "strandbeest-core";
import { call } from "./api";
import {
	branchDesign,
	editor,
	openDocument,
	removeCatalogDesign,
	renameCatalogDesign,
	upsertCatalogDesign,
} from "./editor.svelte";
import { t } from "./i18n/index.svelte";
import { opLabel } from "./opdocs";
import { STATIC } from "./static";

let {
	onmessage,
}: { onmessage: (text: string, kind?: "info" | "error") => void } = $props();

interface RunRow {
	id: string;
	created_at?: string;
	design_id?: string | null;
	design_name: string;
	mean_speed?: number;
	cost_of_transport?: number;
	valid?: number;
}

interface ProfileRow {
	id: string;
	kind?: string;
	created_at?: string;
	design_id?: string | null;
	run_ids?: string[];
}

interface ProvenanceGraph {
	target_kind: string;
	target_id: string;
	nodes: { kind: string; id: string; label?: string }[];
	edges: {
		src_kind: string;
		src_id: string;
		dst_kind: string;
		dst_id: string;
		rel: string;
	}[];
}

let query = $state("");
let runs = $state<RunRow[]>([]);
let profiles = $state<ProfileRow[]>([]);
let prov = $state<ProvenanceGraph | null>(null);
let compareA = $state<string>("");
let compareB = $state<string>("");
let renamingId = $state<string | null>(null);
let renameInput = $state<string>("");

const designs = $derived(Object.values(editor.catalog));
const byId = $derived(new Map(designs.map((d) => [d.id, d])));

const filteredDesigns = $derived.by(() => {
	const q = query.trim().toLowerCase();
	if (!q) return designs;
	return designs.filter((d) => {
		const hay = [
			d.name,
			d.id,
			d.manufacturing?.material ?? "",
			`${d.walker?.legs ?? ""}legs`,
			...(d.aliases ?? []),
		]
			.join(" ")
			.toLowerCase();
		return hay.includes(q);
	});
});

const treeNodes = $derived(
	flattenGenealogyTree(buildGenealogyTree(filteredDesigns)),
);

const filteredRuns = $derived.by(() => {
	const q = query.trim().toLowerCase();
	return runs.filter((r) => {
		const resolvedName =
			(r.design_id && byId.get(r.design_id)?.name) || r.design_name;
		if (!q) return true;
		return (
			r.id.toLowerCase().includes(q) ||
			resolvedName.toLowerCase().includes(q) ||
			(r.design_id ?? "").toLowerCase().includes(q)
		);
	});
});

const filteredProfiles = $derived.by(() => {
	const q = query.trim().toLowerCase();
	return profiles.filter((p) => {
		if (!q) return true;
		return (
			p.id.toLowerCase().includes(q) ||
			(p.kind ?? "").toLowerCase().includes(q) ||
			(p.design_id ?? "").toLowerCase().includes(q)
		);
	});
});

const diffResult = $derived.by(() => {
	const a = byId.get(compareA);
	const b = byId.get(compareB);
	if (!a || !b || a.id === b.id) return null;
	return diffDesigns(a, b);
});

$effect(() => {
	const curId = editor.design.id;
	const parentId = editor.design.parent?.id;
	if (!compareB || !byId.has(compareB)) {
		compareB = curId;
	}
	if ((!compareA || !byId.has(compareA)) && parentId && byId.has(parentId)) {
		compareA = parentId;
	} else if (!compareA || !byId.has(compareA)) {
		const firstOther = designs.find((d) => d.id !== compareB);
		compareA = firstOther?.id ?? curId;
	}
});

export async function refreshAssets() {
	if (STATIC) return;
	try {
		const [remoteDesigns, remoteRuns, remoteProfiles] = await Promise.all([
			call("/designs?detail=true").catch(() => []),
			call("/runs?limit=30").catch(() => []),
			call("/profiles").catch(() => []),
		]);
		if (Array.isArray(remoteDesigns)) {
			for (const item of remoteDesigns) {
				if (item?.id) {
					try {
						const full = (await call(`/designs/${item.id}`)) as Design;
						if (full?.id && full?.linkage) upsertCatalogDesign(full);
					} catch {
						/* ignore individual fetch failure */
					}
				}
			}
		}
		if (Array.isArray(remoteRuns)) runs = remoteRuns;
		if (Array.isArray(remoteProfiles)) profiles = remoteProfiles;
	} catch {
		/* offline */
	}
}

$effect(() => {
	if (!STATIC) {
		refreshAssets();
	}
});

function handleBranch() {
	const parentId = editor.design.id;
	const child = branchDesign();
	compareA = parentId;
	compareB = child.id;
	if (!STATIC) {
		call("/designs", child).catch(() => {});
	}
	onmessage(t("assets.duplicated", { name: child.name }), "info");
}

function startRename(d: Design) {
	renamingId = d.id;
	renameInput = d.name;
}

async function commitRename(d: Design) {
	const next = renameInput.trim();
	renamingId = null;
	if (!next || next === d.name) return;
	renameCatalogDesign(d.id, next);
	if (!STATIC) {
		try {
			await call(`/designs/${d.id}/rename`, { name: next });
		} catch {
			/* local rename already applied */
		}
	}
	onmessage(t("assets.renamed", { name: next }), "info");
}

async function duplicateDesign(d: Design) {
	if (!STATIC) {
		try {
			const dup = (await call(`/designs/${d.id}/duplicate`, {
				name: `${d.name}-copy`,
			})) as Design;
			if (dup?.id) {
				upsertCatalogDesign(dup);
				openDocument(dup);
				compareA = d.id;
				compareB = dup.id;
				onmessage(t("assets.duplicated", { name: dup.name }), "info");
				return;
			}
		} catch {
			/* fall back to local fork */
		}
	}
	openDocument(d);
	const child = branchDesign(`${d.name}-copy`);
	compareA = d.id;
	compareB = child.id;
	onmessage(t("assets.duplicated", { name: child.name }), "info");
}

async function deleteDesign(d: Design) {
	if (!STATIC) {
		try {
			await fetch(
				`${(await import("./store.svelte")).store.api}/designs/${encodeURIComponent(d.id)}`,
				{ method: "DELETE" },
			);
		} catch {
			/* ignore network error */
		}
	}
	removeCatalogDesign(d.id);
	onmessage(t("assets.deleted", { name: d.name }), "info");
}

async function inspectProvenance(kind: "runs" | "profiles", id: string) {
	if (STATIC) return;
	try {
		prov = (await call(
			`/${kind}/${encodeURIComponent(id)}/provenance`,
		)) as ProvenanceGraph;
	} catch (e) {
		onmessage(e instanceof Error ? e.message : String(e), "error");
	}
}
</script>

<div class="asset-browser">
	<div class="row center bar">
		<input
			type="search"
			class="search"
			placeholder={t("assets.search")}
			bind:value={query}
		/>
		<button class="btn small primary" onclick={handleBranch}>
			{t("assets.branchCurrent")}
		</button>
		{#if !STATIC}
			<button class="btn small" onclick={refreshAssets}>
				{t("common.refresh")}
			</button>
		{/if}
	</div>

	<div class="grid2">
		<div class="pane">
			<h3>{t("genealogy.treeTitle")} · {t("assets.designs", { n: filteredDesigns.length })}</h3>
			{#if treeNodes.length === 0}
				<p class="muted">{t("assets.empty")}</p>
			{:else}
				<ul class="tree">
					{#each treeNodes as node (node.id)}
						{@const doc = byId.get(node.id)}
						{#if doc}
							<li
								class:current={doc.id === editor.design.id}
								style="padding-left: {8 + node.depth * 18}px"
							>
								<div class="node-main">
									<span class="connector">{node.depth > 0 ? "└─" : "●"}</span>
									{#if renamingId === doc.id}
										<input
											type="text"
											size="14"
											bind:value={renameInput}
											onkeydown={(e) => e.key === "Enter" && commitRename(doc)}
										/>
										<button class="btn tiny primary" onclick={() => commitRename(doc)}>
											{t("common.save")}
										</button>
										<button class="btn tiny" onclick={() => (renamingId = null)}>
											{t("common.cancel")}
										</button>
									{:else}
										<button
											class="link-btn"
											onclick={() => openDocument(doc)}
											title={doc.id}
										>
											<b>{doc.name}</b>
										</button>
									{/if}
									<code class="ulid">{doc.id.slice(-6)}</code>
									<span class="tag">{doc.manufacturing.material} · {doc.walker.legs}L</span>
									{#if node.parentId}
										<small class="muted">
											({t("genealogy.branchTag", {
												parent: byId.get(node.parentId)?.name ?? node.parentId.slice(-6),
											})})
										</small>
									{:else}
										<small class="muted">({t("genealogy.rootTag")})</small>
									{/if}
								</div>
								<div class="node-actions">
									<button
										class="btn tiny"
										class:active-ab={compareA === doc.id}
										onclick={() => (compareA = doc.id)}
									>
										{t("genealogy.compareA")}
									</button>
									<button
										class="btn tiny"
										class:active-ab={compareB === doc.id}
										onclick={() => (compareB = doc.id)}
									>
										{t("genealogy.compareB")}
									</button>
									<button class="btn tiny" onclick={() => startRename(doc)}>
										{t("assets.Rename")}
									</button>
									<button class="btn tiny" onclick={() => duplicateDesign(doc)}>
										{t("assets.Duplicate")}
									</button>
									{#if designs.length > 1}
										<button class="btn tiny" onclick={() => deleteDesign(doc)}>
											{t("assets.Delete")}
										</button>
									{/if}
								</div>
							</li>
						{/if}
					{/each}
				</ul>
			{/if}
		</div>

		<div class="pane">
			<h3>{t("genealogy.diffTitle")}</h3>
			<div class="row center ab-pickers">
				<label>
					<span>A:</span>
					<select bind:value={compareA}>
						{#each designs as d (d.id)}
							<option value={d.id}>{d.name} ({d.id.slice(-6)})</option>
						{/each}
					</select>
				</label>
				<span>→</span>
				<label>
					<span>B:</span>
					<select bind:value={compareB}>
						{#each designs as d (d.id)}
							<option value={d.id}>{d.name} ({d.id.slice(-6)})</option>
						{/each}
					</select>
				</label>
			</div>

			{#if !diffResult}
				<p class="muted">{t("genealogy.diffEmpty")}</p>
			{:else if diffResult.params.length === 0 && diffResult.properties.length === 0}
				<p class="muted">{t("genealogy.diffIdentical")}</p>
			{:else}
				<div class="diff-box">
					<h4>{t("genealogy.diffOpsTitle", { n: diffResult.operations.length })}</h4>
					<ul class="ops-list">
						{#each diffResult.operations as o (o.id)}
							<li>
								<b>{opLabel(o.type)}</b>
								<code>{JSON.stringify(o.args)}</code>
								{#if o.reason}<em>({o.reason})</em>{/if}
							</li>
						{/each}
					</ul>

					<h4>{t("genealogy.diffParamsTitle")}</h4>
					<table class="diff-table">
						<thead>
							<tr>
								<th>{t("genealogy.col.param")}</th>
								<th>{t("genealogy.col.before")}</th>
								<th>{t("genealogy.col.after")}</th>
								<th>{t("genealogy.col.delta")}</th>
							</tr>
						</thead>
						<tbody>
							{#each diffResult.params as p (p.name)}
								<tr>
									<td><code>{p.name}</code></td>
									<td>{p.before !== undefined ? p.before.toFixed(2) : "—"}</td>
									<td>{p.after !== undefined ? p.after.toFixed(2) : "—"}</td>
									<td class:pos={(p.delta ?? 0) > 0} class:neg={(p.delta ?? 0) < 0}>
										{p.delta !== undefined
											? `${p.delta > 0 ? "+" : ""}${p.delta.toFixed(2)}`
											: "—"}
									</td>
								</tr>
							{/each}
							{#each diffResult.properties as prop (prop.path)}
								<tr>
									<td><code>{prop.path}</code></td>
									<td>{String(prop.before ?? "—")}</td>
									<td>{String(prop.after ?? "—")}</td>
									<td>—</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</div>

	{#if !STATIC && (filteredRuns.length > 0 || filteredProfiles.length > 0)}
		<div class="grid2 sub-assets">
			<div class="pane">
				<h3>{t("assets.runs", { n: filteredRuns.length })}</h3>
				<ul class="compact-list">
					{#each filteredRuns as r (r.id)}
						{@const resolvedDesignName =
							(r.design_id && byId.get(r.design_id)?.name) || r.design_name}
						<li>
							<code>{r.id}</code>
							<b>{resolvedDesignName}</b>
							{#if r.mean_speed !== undefined}
								<span class="tag">{r.mean_speed.toFixed(3)} m/s</span>
							{/if}
							<button class="btn tiny" onclick={() => inspectProvenance("runs", r.id)}>
								{t("assets.provenance")}
							</button>
						</li>
					{/each}
				</ul>
			</div>
			<div class="pane">
				<h3>{t("assets.profiles", { n: filteredProfiles.length })}</h3>
				<ul class="compact-list">
					{#each filteredProfiles as p (p.id)}
						<li>
							<code>{p.id}</code>
							<span class="tag">{p.kind ?? "calibration"}</span>
							{#if p.design_id && byId.has(p.design_id)}
								<b>{byId.get(p.design_id)?.name}</b>
							{/if}
							<button class="btn tiny" onclick={() => inspectProvenance("profiles", p.id)}>
								{t("assets.provenance")}
							</button>
						</li>
					{/each}
				</ul>
			</div>
		</div>
	{/if}

	{#if prov}
		<div class="pane prov-box">
			<div class="row center" style="justify-content: space-between">
				<h4>{t("assets.provenance")}: <code>{prov.target_kind}:{prov.target_id}</code></h4>
				<button class="btn tiny" onclick={() => (prov = null)}>{t("common.closeParen")}</button>
			</div>
			<ul class="compact-list">
				{#each prov.edges as e, idx (idx)}
					<li>
						<code>{e.src_kind}:{byId.get(e.src_id)?.name ?? e.src_id}</code>
						<span>—[{e.rel}]→</span>
						<code>{e.dst_kind}:{byId.get(e.dst_id)?.name ?? e.dst_id}</code>
					</li>
				{/each}
			</ul>
		</div>
	{/if}
</div>

<style>
	.asset-browser { display: flex; flex-direction: column; gap: 12px; margin-top: 8px; }
	.bar { justify-content: space-between; flex-wrap: wrap; gap: 8px; }
	.search { flex: 1; min-width: 220px; padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--ink); }
	.pane { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: var(--bg); }
	.pane h3 { margin: 0 0 8px 0; font-size: 14px; }
	.pane h4 { margin: 8px 0 4px 0; font-size: 13px; }
	.tree, .compact-list, .ops-list { list-style: none; margin: 0; padding: 0; max-height: 240px; overflow: auto; }
	.tree li, .compact-list li { display: flex; justify-content: space-between; align-items: center; gap: 6px; padding: 5px 6px; border-bottom: 1px solid var(--line); flex-wrap: wrap; font-size: 13px; }
	.tree li:last-child, .compact-list li:last-child { border-bottom: none; }
	.tree li.current { background: rgba(230, 126, 34, 0.08); border-radius: 4px; }
	.node-main, .node-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
	.connector { color: var(--muted); font-family: monospace; }
	.link-btn { background: none; border: none; padding: 0; color: var(--ink); cursor: pointer; font: inherit; text-align: left; }
	.link-btn:hover { color: var(--accent); text-decoration: underline; }
	.ulid { font-size: 11px; color: var(--muted); }
	.tag { font-size: 11px; padding: 1px 6px; border-radius: 8px; border: 1px solid var(--line); color: var(--muted); }
	.btn.tiny { padding: 2px 6px; font-size: 11px; }
	.btn.active-ab { border-color: var(--accent); color: var(--accent); font-weight: 600; }
	.ab-pickers label { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; }
	.diff-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 4px; }
	.diff-table th, .diff-table td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
	.pos { color: var(--ok); }
	.neg { color: var(--bad); }
	.ops-list li { font-size: 12px; padding: 2px 0; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
</style>
