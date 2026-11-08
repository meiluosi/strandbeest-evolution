import { t } from "./i18n/index.svelte";
import { store } from "./store.svelte";

const errorKeys: Record<string, string> = {
	measurement_id_conflict: "lab.error.measurementConflict",
	calibration_measurement_invalid: "lab.error.measurementInvalid",
	calibration_profile_invalid: "lab.error.profileInvalid",
	calibration_parameters_invalid: "lab.error.parametersInvalid",
	invalid_harness_document: "harness.error.invalid",
	unknown_asset_reference: "harness.error.unknownAsset",
	asset_reference_mismatch: "harness.error.assetMismatch",
	revision_base_conflict: "harness.error.revisionConflict",
	snapshot_source_changed: "harness.error.sourceChanged",
};

export async function call<T = any>(path: string, body?: unknown): Promise<T> {
	const r = await fetch(store.api + path, {
		method: body === undefined ? "GET" : "POST",
		headers: { "content-type": "application/json" },
		body: body === undefined ? undefined : JSON.stringify(body),
	});
	if (!r.ok) {
		const raw = await r.text();
		let code = "";
		try {
			const error = JSON.parse(raw);
			code = error.detail?.code ?? error.code ?? "";
		} catch {}
		const key = errorKeys[code];
		throw new Error(key ? t(key) : `${r.status} ${raw}`);
	}
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
		if (j.status === "failed") throw new Error(j.error ?? t("api.jobFailed"));
		if (j.status === "cancelled") throw new Error(t("api.jobCancelled"));
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
