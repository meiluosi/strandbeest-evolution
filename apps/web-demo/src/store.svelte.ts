import { currentDesign, editor } from "./editor.svelte";

const DEFAULT_API: string =
	import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

function loadApi(): string {
	try {
		return localStorage.getItem("strandbeest-api") ?? DEFAULT_API;
	} catch {
		return DEFAULT_API;
	}
}

/** State shared by every tab that is not the design: where the backend is. The design lives in editor.svelte.ts. */
export const store = $state({ api: loadApi() });

/** Read-only facade over the design being edited; change it only with the operations in editor.svelte.ts. */
export const view = {
	get name() {
		return editor.design.name;
	},
	get designId() {
		return editor.design.id;
	},
	get legs() {
		return editor.design.walker.legs;
	},
	get unitMm() {
		return editor.design.walker.unit_m * 1000;
	},
	get clearance() {
		return editor.design.manufacturing.clearance_mm;
	},
	get linkage() {
		return editor.design.linkage;
	},
};

export { currentDesign };

export function setApi(url: string) {
	store.api = url;
	try {
		localStorage.setItem("strandbeest-api", url);
	} catch {
		/* storage unavailable: keep it in memory only */
	}
}
