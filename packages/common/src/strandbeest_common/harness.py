"""Validation and content identity for the minimal Harness protocol and dataset contracts."""

from __future__ import annotations

from typing import Any

from .hashing import content_hash
from .schemas import validate

_REVISION_PAYLOAD = (
    "question",
    "inputs",
    "conditions",
    "trials",
    "evaluation_suite",
    "budget",
    "permission_policy",
)
_SNAPSHOT_PAYLOAD = ("sources", "observation", "split", "transforms", "total_samples")


def revision_payload(doc: dict[str, Any]) -> dict[str, Any]:
    payload = {key: doc[key] for key in _REVISION_PAYLOAD}
    if "base_id" in doc:
        payload["base_id"] = doc["base_id"]
    return payload


def snapshot_payload(doc: dict[str, Any]) -> dict[str, Any]:
    return {key: doc[key] for key in _SNAPSHOT_PAYLOAD}


def revision_digest(doc: dict[str, Any]) -> str:
    return content_hash(revision_payload(doc))


def snapshot_digest(doc: dict[str, Any]) -> str:
    return content_hash(snapshot_payload(doc))


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    return {value for value in values if value in seen or seen.add(value)}


def validate_experiment_revision(doc: dict[str, Any]) -> None:
    validate("experiment-revision", doc)
    conditions = doc["conditions"]
    trials = doc["trials"]
    condition_ids = {condition["id"] for condition in conditions}
    for label, values in (
        ("condition id", [condition["id"] for condition in conditions]),
        ("condition key", [condition["key"] for condition in conditions]),
        ("trial id", [trial["id"] for trial in trials]),
        ("trial key", [trial["key"] for trial in trials]),
    ):
        if duplicates := _duplicates(values):
            raise ValueError(f"duplicate {label}: {sorted(duplicates)}")
    unknown = sorted({trial["condition_id"] for trial in trials} - condition_ids)
    if unknown:
        raise ValueError(f"trial references unknown condition: {unknown}")
    if missing := sorted(condition_ids - {trial["condition_id"] for trial in trials}):
        raise ValueError(f"condition has no planned trial: {missing}")
    if len(trials) > doc["budget"]["max_trials"]:
        raise ValueError("planned trials exceed budget.max_trials")
    if doc["digest"] != revision_digest(doc):
        raise ValueError("experiment revision digest does not match its immutable payload")


def validate_dataset_snapshot(doc: dict[str, Any]) -> None:
    validate("dataset-snapshot", doc)
    sources = doc["sources"]
    if duplicates := _duplicates([source["episode_id"] for source in sources]):
        raise ValueError(f"duplicate episode id: {sorted(duplicates)}")
    expected_channels = doc["observation"]["channels"]
    if duplicates := _duplicates(expected_channels):
        raise ValueError(f"duplicate observation channel: {sorted(duplicates)}")
    for source in sources:
        if source["channels"] != expected_channels:
            raise ValueError(f"source {source['episode_id']} does not match the observation contract")
    assignments = doc["split"]["assignments"]
    assigned = [assignment["group_id"] for assignment in assignments]
    if duplicates := _duplicates(assigned):
        raise ValueError(f"group appears in more than one split: {sorted(duplicates)}")
    source_groups = {source["group_id"] for source in sources}
    if set(assigned) != source_groups:
        raise ValueError("split assignments must cover every source group exactly once")
    splits = {assignment["split"] for assignment in assignments}
    if not {"train", "test"}.issubset(splits):
        raise ValueError("split requires at least one train group and one test group")
    if doc["total_samples"] != sum(source["sample_count"] for source in sources):
        raise ValueError("total_samples does not match the source manifest")
    if doc["digest"] != snapshot_digest(doc):
        raise ValueError("dataset snapshot digest does not match its immutable payload")
