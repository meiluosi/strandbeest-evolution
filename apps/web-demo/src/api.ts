import { store } from "./store.svelte";

export async function call<T = any>(path: string, body?: unknown): Promise<T> {
	const r = await fetch(store.api + path, {
		method: body === undefined ? "GET" : "POST",
		headers: { "content-type": "application/json" },
		body: body === undefined ? undefined : JSON.stringify(body),
	});
	if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
	return r.json();
}

/** Submit a job-producing POST and wait for it; `onTick` gets the job after each poll. */
export async function runJob<T = any>(
	path: string,
	body: unknown,
	onTick?: (status: string) => void,
): Promise<T> {
	const { job_id } = await call(path, body);
	for (;;) {
		const j = await call(`/jobs/${job_id}`);
		onTick?.(j.status);
		if (j.status === "failed") throw new Error(j.error);
		if (j.status === "done") return j.result as T;
		await new Promise((r) => setTimeout(r, 1000));
	}
}

export function download(
	filename: string,
	text: string,
	type = "application/json",
) {
	const a = document.createElement("a");
	a.href = URL.createObjectURL(new Blob([text], { type }));
	a.download = filename;
	a.click();
	URL.revokeObjectURL(a.href);
}
