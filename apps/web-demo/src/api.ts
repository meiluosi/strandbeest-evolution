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

export interface Job {
	id: string;
	kind: string;
	status: string;
	result: any;
	error: string | null;
	progress: { done: number; total: number; message: string };
}

/** Submit a job-producing POST and wait for it; `onTick` gets the job after every poll. */
export async function runJob<T = any>(
	path: string,
	body: unknown,
	onTick?: (job: Job) => void,
): Promise<T> {
	const { job_id } = await call(path, body);
	onTick?.({
		id: job_id,
		kind: "",
		status: "queued",
		result: null,
		error: null,
		progress: { done: 0, total: 0, message: "" },
	});
	for (;;) {
		const j: Job = await call(`/jobs/${job_id}`);
		onTick?.(j);
		if (j.status === "failed") throw new Error(j.error ?? "任务失败");
		if (j.status === "cancelled") throw new Error("已取消");
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
