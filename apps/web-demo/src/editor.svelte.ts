import {
	type Actor,
	type Design,
	defaultDesign,
	GuardError,
	History,
	type LinkageSpec,
	makeGuard,
	makeOp,
	OPS,
	OpError,
	type Operation,
	type Problem,
	withLength,
} from "strandbeest-core";
import designSchema from "../../../schemas/design.schema.json";

/**
 * The editor state (E3-04). The design is never edited directly: every change is an operation committed to a History
 * (log + undo/redo) through the validity guard, so the log is the source of truth and the design is its fold. The log is
 * kept in localStorage so a refresh keeps the history; if it can no longer be replayed we keep what still applies.
 */
const STORAGE_KEY = "strandbeest-editor-v1";
const guard = makeGuard(designSchema as Record<string, unknown>);
export const HUMAN: Actor = { kind: "human", id: "web" };

interface Saved {
	v: 1;
	base: Design;
	steps: Operation[][];
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function load(): { history: History; notice: string | null } | null {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return null;
		const saved = JSON.parse(raw) as Saved;
		if (saved.v !== 1 || !saved.base || !Array.isArray(saved.steps))
			return null;
		const history = new History(saved.base, [guard]);
		let kept = 0;
		for (const step of saved.steps) {
			try {
				history.commitMany(step);
				kept++;
			} catch {
				return { history, notice: `${kept}/${saved.steps.length}` };
			}
		}
		return { history, notice: null };
	} catch {
		return null; // private mode, corrupt data: start fresh
	}
}

let history: History;
const restored = load();
if (restored) history = restored.history;
else history = new History(defaultDesign(), [guard]);

export interface EditResult {
	ok: boolean;
	message?: string;
	problems?: Problem[];
}

/** Reactive view of the history. Components read these; they change only through the functions below. */
export const editor = $state({
	design: clone(history.design),
	steps: history.steps.map((s) => clone(s)) as Operation[][],
	canUndo: history.canUndo,
	canRedo: history.canRedo,
	/** a draft that is shown but not committed (slider or point being dragged) */
	preview: null as Operation[] | null,
	/** set when a saved log could only be partly replayed: how many steps were kept */
	restoredPartly: restored?.notice ?? null,
});

function sync() {
	editor.design = clone(history.design);
	editor.steps = history.steps.map((s) => clone(s));
	editor.canUndo = history.canUndo;
	editor.canRedo = history.canRedo;
	editor.preview = null;
	try {
		localStorage.setItem(
			STORAGE_KEY,
			JSON.stringify({
				v: 1,
				base: history.base,
				steps: history.steps,
			} satisfies Saved),
		);
	} catch {
		/* storage unavailable: the history lives only as long as the page */
	}
}

function describe(e: unknown): EditResult {
	if (e instanceof GuardError)
		return { ok: false, message: e.message, problems: e.problems };
	if (e instanceof OpError) return { ok: false, message: e.message };
	throw e;
}

export function op(
	type: Operation["type"],
	args: Record<string, unknown>,
	reason = "",
	actor: Actor = HUMAN,
): Operation {
	return makeOp(type, args, { actor, reason });
}

/** Commit operations as ONE undo step; nothing changes if any is rejected. */
export function commit(ops: Operation[]): EditResult {
	try {
		history.commitMany(ops);
		sync();
		return { ok: true };
	} catch (e) {
		editor.preview = null;
		return describe(e);
	}
}

export const edit = (
	type: Operation["type"],
	args: Record<string, unknown>,
	reason = "",
	actor: Actor = HUMAN,
) => commit([op(type, args, reason, actor)]);

/** Set a length by handle: a named param uses set_param, an inline number uses set_length. */
export function setLength(key: string, value: number, reason = ""): EditResult {
	return edit(
		key in history.design.linkage.params ? "set_param" : "set_length",
		key in history.design.linkage.params
			? { name: key, value }
			: { key, value },
		reason,
	);
}

export function setProperty(path: string, value: unknown): EditResult {
	return edit("set_property", { path, value });
}

export function undo(): EditResult {
	try {
		history.undo();
		sync();
		return { ok: true };
	} catch (e) {
		return describe(e);
	}
}

export function redo(): EditResult {
	try {
		history.redo();
		sync();
		return { ok: true };
	} catch (e) {
		return describe(e);
	}
}

/** Start a new document (new base, empty log): opening a file, loading an example, starting over. */
export function openDocument(doc: Design) {
	history = new History(doc, [guard]);
	editor.restoredPartly = null;
	sync();
}

export function newFromLinkage(linkage: LinkageSpec, name = "untitled") {
	openDocument(defaultDesign(clone(linkage), name));
}

/** The operations of the whole log, flat, as an OpLog document (schemas/ops.schema.json). */
export function exportLog() {
	return {
		schema_version: 1,
		design_id: history.base.id,
		base: history.base,
		ops: history.ops,
	};
}

export function currentDesign(): Design {
	return clone(history.design);
}

/** What the draft would look like, without committing or guarding it (only for display while dragging). */
export function previewDesign(): Design {
	if (!editor.preview) return editor.design;
	const d = clone(editor.design);
	for (const o of editor.preview) {
		try {
			OPS[o.type]?.apply(d, o.args as Record<string, unknown>);
		} catch {
			/* a draft that does not apply is simply not shown */
		}
	}
	return d;
}

/** Spec being shown: the committed linkage, or the draft over it. */
export function shownLinkage(): LinkageSpec {
	return previewDesign().linkage;
}

export { withLength };
