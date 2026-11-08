import { call } from "./api";

export type AssetKind =
	| "design"
	| "run"
	| "measurement"
	| "profile"
	| "dataset_snapshot";
export type Split = "train" | "development" | "test";

export interface AssetRef {
	kind: AssetKind;
	id: string;
	digest: string;
}

export interface Condition {
	id: string;
	key: string;
	label: string;
	role: "baseline" | "learned" | "control";
	design?: AssetRef;
	parameters: Record<string, unknown>;
}

export interface Trial {
	id: string;
	condition_id: string;
	key: string;
	seed: number;
	purpose: "initial" | "independent_replication";
}

export interface ExperimentRevision {
	schema_version: 1;
	id: string;
	experiment_id: string;
	revision: number;
	base_id?: string;
	question: string;
	inputs: {
		design: AssetRef;
		scenario?: { document: Record<string, unknown>; digest: string };
		source_runs: AssetRef[];
		dataset_snapshot?: AssetRef;
	};
	conditions: Condition[];
	trials: Trial[];
	evaluation_suite: { key: string; revision: number; metrics: string[] };
	budget: { max_trials: number; max_compute_seconds: number };
	permission_policy: {
		mode: "manual_only";
		requires_execution_authorization: true;
	};
	created: string;
	digest: string;
}

export interface Experiment {
	schema_version: 1;
	id: string;
	title: string;
	status: "draft";
	current_revision: number;
	current_revision_id: string;
	created: string;
}

export interface SnapshotSource {
	run: AssetRef;
	episode_id: string;
	group_id: string;
	arrays_file: string;
	arrays_sha256: string;
	sample_count: number;
	channels: string[];
}

export interface DatasetSnapshot {
	schema_version: 1;
	id: string;
	sources: SnapshotSource[];
	observation: { time_unit: "s"; channels: string[] };
	split: {
		group_by: "design_id";
		assignments: { group_id: string; split: Split }[];
	};
	transforms: [];
	total_samples: number;
	created: string;
	digest: string;
}

export interface RunSummary {
	id: string;
	design_id: string;
	design_name: string;
	created: string;
	stalled: boolean;
}

export interface LineageEdge {
	child_id: string;
	child_kind: string;
	parent_id: string;
	parent_kind: string;
	relation: string;
}

export interface ProtocolInput {
	question: string;
	inputs: ExperimentRevision["inputs"];
	conditions: Omit<Condition, "id">[];
	trials: {
		condition_key: string;
		key: string;
		seed: number;
		purpose: Trial["purpose"];
	}[];
	evaluation_suite: ExperimentRevision["evaluation_suite"];
	budget: ExperimentRevision["budget"];
}

const root = "/api/harness/v1";

export const harnessApi = {
	listExperiments: () => call<Experiment[]>(`${root}/experiments`),
	getExperiment: (id: string) => call<Experiment>(`${root}/experiments/${id}`),
	getRevision: (id: string) =>
		call<ExperimentRevision>(`${root}/experiment-revisions/${id}`),
	createExperiment: (title: string, protocol: ProtocolInput) =>
		call<{ experiment: Experiment; revision: ExperimentRevision }>(
			`${root}/experiments`,
			{ title, ...protocol },
		),
	createRevision: (
		experimentId: string,
		baseId: string,
		protocol: ProtocolInput,
	) =>
		call<ExperimentRevision>(`${root}/experiments/${experimentId}/revisions`, {
			base_id: baseId,
			...protocol,
		}),
	validateRevision: (id: string) =>
		call<{ ok: true; digest: string; execution_authorized: false }>(
			`${root}/experiment-revisions/${id}/validate`,
			{},
		),
	assetReference: (kind: AssetKind, id: string) =>
		call<AssetRef>(`${root}/assets/${kind}/${id}/reference`),
	createSnapshot: (input: {
		sources: { run_id: string; arrays_file: string }[];
		channels: string[];
		assignments: { group_id: string; split: Split }[];
	}) =>
		call<DatasetSnapshot>(`${root}/dataset-snapshots`, {
			sources: input.sources,
			observation: { time_unit: "s", channels: input.channels },
			split: { assignments: input.assignments },
		}),
	getSnapshot: (id: string) =>
		call<DatasetSnapshot>(`${root}/dataset-snapshots/${id}`),
	validateSnapshot: (id: string) =>
		call<{ ok: true; digest: string; total_samples: number }>(
			`${root}/dataset-snapshots/${id}/validate`,
			{},
		),
	lineage: (id: string) =>
		call<{ asset_id: string; edges: LineageEdge[] }>(
			`${root}/assets/${id}/lineage`,
		),
};
