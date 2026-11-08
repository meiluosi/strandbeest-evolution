import { describe, expect, it } from "vitest";
import {
	canCreateSnapshot,
	defaultAssignments,
	groupRuns,
	revisionDifferences,
} from "./harness";
import type { ExperimentRevision, RunSummary } from "./harness-api";

const revision = {
	schema_version: 1,
	id: "revision-2",
	experiment_id: "experiment-1",
	revision: 2,
	base_id: "revision-1",
	question: "Does it reproduce the stride?",
	inputs: {
		design: { kind: "design", id: "design-1", digest: "sha256:a" },
		source_runs: [],
	},
	conditions: [
		{
			id: "condition-2",
			key: "baseline",
			label: "Baseline",
			role: "baseline",
			parameters: {},
		},
	],
	trials: [
		{
			id: "trial-2",
			condition_id: "condition-2",
			key: "independent",
			seed: 8,
			purpose: "independent_replication",
		},
	],
	evaluation_suite: { key: "stride", revision: 1, metrics: ["stride_per_rev"] },
	budget: { max_trials: 4, max_compute_seconds: 60 },
	permission_policy: {
		mode: "manual_only",
		requires_execution_authorization: true,
	},
	created: "2026-11-06T00:00:00+00:00",
	digest: "sha256:test",
} satisfies ExperimentRevision;

const base = {
	...revision,
	id: "revision-1",
	base_id: undefined,
	trials: [
		{
			id: "trial-1",
			condition_id: "condition-1",
			key: "initial",
			seed: 7,
			purpose: "initial",
		},
	],
} as ExperimentRevision;

const runs = [
	{ id: "run-1", design_id: "design-1", design_name: "One" },
	{ id: "run-2", design_id: "design-1", design_name: "One" },
	{ id: "run-3", design_id: "design-2", design_name: "Two" },
] as RunSummary[];

describe("Harness protocol view models", () => {
	it("compares scientific content rather than immutable IDs", () => {
		const differences = revisionDifferences(revision, base);
		expect(differences.map((row) => row.key)).toEqual(["trials"]);
		expect(differences[0]?.after).toContain("independent_replication");
	});

	it("keeps independent replication visible with unchanged parameters", () => {
		expect(
			revisionDifferences({ ...revision, trials: base.trials }, base),
		).toEqual([]);
	});

	it("compares scenario, condition labels and condition-level designs", () => {
		const differences = revisionDifferences(
			{
				...revision,
				inputs: {
					...revision.inputs,
					scenario: { document: { seed: 2 }, digest: "sha256:scenario-2" },
				},
				conditions: revision.conditions.map((condition) => ({
					...condition,
					label: "Independent baseline",
					design: {
						kind: "design",
						id: "design-2",
						digest: "sha256:design-2",
					},
				})),
			},
			base,
		);
		expect(differences.map((row) => row.key)).toEqual([
			"scenario",
			"conditions",
			"trials",
		]);
	});

	it("groups selected runs by design without mixing episodes", () => {
		expect(groupRuns(runs, new Set(["run-1", "run-2", "run-3"]))).toEqual([
			{ groupId: "design-1", name: "One", runIds: ["run-1", "run-2"] },
			{ groupId: "design-2", name: "Two", runIds: ["run-3"] },
		]);
	});

	it("requires exact train/test group coverage", () => {
		const assignments = defaultAssignments(["design-1", "design-2"]);
		expect(canCreateSnapshot(["design-1", "design-2"], assignments)).toBe(true);
		expect(canCreateSnapshot(["design-1"], assignments.slice(0, 1))).toBe(
			false,
		);
		expect(
			canCreateSnapshot(
				["design-1", "design-2"],
				assignments.map((row) => ({ ...row, split: "train" })),
			),
		).toBe(false);
	});
});
