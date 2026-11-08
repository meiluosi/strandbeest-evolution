import type { ExperimentRevision, RunSummary, Split } from "./harness-api";

export interface RevisionDifference {
	key: string;
	before: string;
	after: string;
}

function same(a: unknown, b: unknown): boolean {
	return JSON.stringify(a) === JSON.stringify(b);
}

function value(input: unknown): string {
	return typeof input === "string" ? input : JSON.stringify(input);
}

export function revisionDifferences(
	current: ExperimentRevision,
	base?: ExperimentRevision,
): RevisionDifference[] {
	if (!base) return [];
	const rows: [string, unknown, unknown][] = [
		["question", base.question, current.question],
		["design", base.inputs.design.digest, current.inputs.design.digest],
		["sourceRuns", base.inputs.source_runs, current.inputs.source_runs],
		[
			"snapshot",
			base.inputs.dataset_snapshot?.digest ?? "—",
			current.inputs.dataset_snapshot?.digest ?? "—",
		],
		[
			"scenario",
			base.inputs.scenario?.digest ?? "—",
			current.inputs.scenario?.digest ?? "—",
		],
		[
			"conditions",
			base.conditions.map(({ key, label, role, design, parameters }) => ({
				key,
				label,
				role,
				design: design?.digest,
				parameters,
			})),
			current.conditions.map(({ key, label, role, design, parameters }) => ({
				key,
				label,
				role,
				design: design?.digest,
				parameters,
			})),
		],
		[
			"trials",
			base.trials.map(({ key, seed, purpose }) => ({ key, seed, purpose })),
			current.trials.map(({ key, seed, purpose }) => ({ key, seed, purpose })),
		],
		["evaluation", base.evaluation_suite, current.evaluation_suite],
		["budget", base.budget, current.budget],
	];
	return rows
		.filter(([, before, after]) => !same(before, after))
		.map(([key, before, after]) => ({
			key,
			before: value(before),
			after: value(after),
		}));
}

export function groupRuns(
	runs: RunSummary[],
	selected: Set<string>,
): { groupId: string; name: string; runIds: string[] }[] {
	const groups = new Map<
		string,
		{ groupId: string; name: string; runIds: string[] }
	>();
	for (const run of runs) {
		if (!selected.has(run.id)) continue;
		const group = groups.get(run.design_id) ?? {
			groupId: run.design_id,
			name: run.design_name,
			runIds: [],
		};
		group.runIds.push(run.id);
		groups.set(run.design_id, group);
	}
	return [...groups.values()];
}

export function defaultAssignments(
	groupIds: string[],
): { group_id: string; split: Split }[] {
	return groupIds.map((group_id, index) => ({
		group_id,
		split: index === 0 ? "train" : "test",
	}));
}

export function canCreateSnapshot(
	groupIds: string[],
	assignments: { group_id: string; split: Split }[],
): boolean {
	if (groupIds.length < 2 || assignments.length !== groupIds.length)
		return false;
	const assigned = assignments.map((assignment) => assignment.group_id);
	const splits = new Set(assignments.map((assignment) => assignment.split));
	return (
		new Set(assigned).size === groupIds.length &&
		groupIds.every((id) => assigned.includes(id)) &&
		splits.has("train") &&
		splits.has("test")
	);
}
