import {
	type Design,
	defaultDesign,
	JANSEN_LENGTHS,
	type JansenParams,
} from "strandbeest-core";

const DEFAULT_API: string =
	import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

function loadApi(): string {
	try {
		return localStorage.getItem("strandbeest-api") ?? DEFAULT_API;
	} catch {
		return DEFAULT_API;
	}
}

/** State shared by every tab: the design being edited and where the backend is. */
export const store = $state({
	api: loadApi(),
	params: { ...JANSEN_LENGTHS } as JansenParams,
	name: "jansen-small-6leg",
	legs: 6,
	unitMm: 2,
	clearance: 0.3,
});

export function currentDesign(): Design {
	const d = defaultDesign(store.params, store.name);
	d.walker.legs = store.legs;
	d.walker.unit_m = store.unitMm / 1000;
	d.manufacturing.clearance_mm = store.clearance;
	return d;
}

export function setApi(url: string) {
	store.api = url;
	try {
		localStorage.setItem("strandbeest-api", url);
	} catch {
		/* storage unavailable: keep it in memory only */
	}
}
