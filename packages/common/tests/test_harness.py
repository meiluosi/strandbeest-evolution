import copy
import json

import pytest

from strandbeest_common.harness import (
    revision_digest,
    snapshot_digest,
    validate_dataset_snapshot,
    validate_experiment_revision,
)
from strandbeest_common.schemas import schema_dir


def revision():
    return json.loads((schema_dir() / "examples" / "experiment-revision-basic.json").read_text())


def snapshot():
    return json.loads((schema_dir() / "examples" / "dataset-snapshot-basic.json").read_text())


def reseal_revision(doc):
    doc["digest"] = revision_digest(doc)
    return doc


def reseal_snapshot(doc):
    doc["digest"] = snapshot_digest(doc)
    return doc


def test_revision_rejects_digest_tampering():
    doc = revision()
    doc["question"] = "A changed question"
    with pytest.raises(ValueError, match="digest"):
        validate_experiment_revision(doc)


@pytest.mark.parametrize("kind", ["condition id", "condition key", "trial id", "trial key"])
def test_revision_rejects_duplicate_protocol_identity(kind):
    doc = revision()
    if kind.startswith("condition"):
        doc["conditions"].append(copy.deepcopy(doc["conditions"][0]))
        doc["conditions"][1]["id"] = "000000000066QFKTWME86F44NH"
        doc["conditions"][1]["key"] = "control"
        if kind == "condition id":
            doc["conditions"][1]["id"] = doc["conditions"][0]["id"]
        else:
            doc["conditions"][1]["key"] = doc["conditions"][0]["key"]
    else:
        doc["trials"].append(copy.deepcopy(doc["trials"][0]))
        doc["trials"][1]["id"] = "0000000000KX1ZGYJ0BSG2QCH1"
        doc["trials"][1]["key"] = "trial-2"
        if kind == "trial id":
            doc["trials"][1]["id"] = doc["trials"][0]["id"]
        else:
            doc["trials"][1]["key"] = doc["trials"][0]["key"]
    reseal_revision(doc)
    with pytest.raises(ValueError, match=f"duplicate {kind}"):
        validate_experiment_revision(doc)


def test_revision_rejects_unknown_condition_and_budget_overflow():
    doc = revision()
    doc["trials"][0]["condition_id"] = "000000000066QFKTWME86F44NH"
    reseal_revision(doc)
    with pytest.raises(ValueError, match="unknown condition"):
        validate_experiment_revision(doc)
    doc = revision()
    doc["budget"]["max_trials"] = 2
    doc["trials"].append({**doc["trials"][0], "id": "0000000000KX1ZGYJ0BSG2QCH1", "key": "trial-2"})
    reseal_revision(doc)
    doc["budget"]["max_trials"] = 1
    doc["digest"] = revision_digest(doc)
    with pytest.raises(ValueError, match="exceed"):
        validate_experiment_revision(doc)


def test_snapshot_rejects_group_leakage_and_unknown_group():
    doc = snapshot()
    doc["split"]["assignments"].append({"group_id": doc["sources"][0]["group_id"], "split": "test"})
    reseal_snapshot(doc)
    with pytest.raises(ValueError, match="more than one split"):
        validate_dataset_snapshot(doc)
    doc = snapshot()
    doc["split"]["assignments"][1]["group_id"] = "0000000000H7P2SF2CAN868KT6"
    reseal_snapshot(doc)
    with pytest.raises(ValueError, match="cover every source group"):
        validate_dataset_snapshot(doc)


def test_snapshot_requires_train_test_and_matching_sample_total():
    doc = snapshot()
    doc["split"]["assignments"][1]["split"] = "development"
    reseal_snapshot(doc)
    with pytest.raises(ValueError, match="train group and one test"):
        validate_dataset_snapshot(doc)
    doc = snapshot()
    doc["total_samples"] += 1
    reseal_snapshot(doc)
    with pytest.raises(ValueError, match="total_samples"):
        validate_dataset_snapshot(doc)


def test_snapshot_rejects_digest_tampering():
    doc = snapshot()
    doc["sources"][0]["arrays_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="digest"):
        validate_dataset_snapshot(doc)
