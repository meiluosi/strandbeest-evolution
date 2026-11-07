import copy
import json
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient

from strandbeest_api import create_app
from strandbeest_api.app import _reindex
from strandbeest_common.hashing import content_hash
from strandbeest_common.ids import legacy_ulid
from strandbeest_common.schemas import schema_dir

EXAMPLES = schema_dir() / "examples"
DESIGN = json.loads((EXAMPLES / "design-jansen-small-6leg.json").read_text())
RUN = json.loads((EXAMPLES / "run-example.json").read_text())


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    yield TestClient(app)
    app.state.workers.stop()


def seed_assets(root, count=2):
    design_ids = []
    run_ids = []
    for index in range(count):
        design = copy.deepcopy(DESIGN)
        design["id"] = legacy_ulid("design", f"harness-design-{index}")
        design["name"] = f"harness-design-{index}"
        (root / "designs" / f"{design['id']}.json").write_text(json.dumps(design))
        run = copy.deepcopy(RUN)
        run["id"] = legacy_ulid("run", f"harness-run-{index}")
        run["design_id"] = design["id"]
        run["design_name"] = design["name"]
        directory = root / "runs" / run["id"]
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(json.dumps(run))
        np.savez(directory / "arrays.npz", t=np.arange(4 + index), psi=np.arange(4 + index) * 0.1)
        design_ids.append(design["id"])
        run_ids.append(run["id"])
    return design_ids, run_ids


def design_ref(design):
    return {"kind": "design", "id": design["id"], "digest": content_hash(design)}


def saved_design(root, design_id):
    return json.loads((root / "designs" / f"{design_id}.json").read_text())


def protocol(design, question="Does the baseline reproduce the source stride?"):
    return {
        "question": question,
        "inputs": {"design": design_ref(design), "source_runs": []},
        "conditions": [{"key": "baseline", "label": "Baseline", "role": "baseline", "parameters": {}}],
        "trials": [{"condition_key": "baseline", "key": "trial-1", "seed": 7, "purpose": "initial"}],
        "evaluation_suite": {"key": "stride", "revision": 1, "metrics": ["stride_per_rev"]},
        "budget": {"max_trials": 4, "max_compute_seconds": 60},
    }


def create_experiment(client, design, question="Does the baseline reproduce the source stride?"):
    response = client.post("/api/harness/v1/experiments", json={"title": "Stride study", **protocol(design, question)})
    assert response.status_code == 201, response.text
    return response.json()


def snapshot_payload(run_ids, assignments=None):
    return {
        "sources": [{"run_id": run_id, "arrays_file": "arrays.npz"} for run_id in run_ids],
        "observation": {"time_unit": "s", "channels": ["t", "psi"]},
        "split": {"assignments": assignments},
    }


def test_experiment_revision_roundtrip_restart_and_independent_trial(client, tmp_path):
    design_ids, _ = seed_assets(tmp_path)
    design = saved_design(tmp_path, design_ids[0])
    created = create_experiment(client, design)
    experiment = created["experiment"]
    revision = created["revision"]
    assert experiment["current_revision_id"] == revision["id"]
    assert client.get(f"/api/harness/v1/experiments/{experiment['id']}").json()["current_revision_id"] == revision["id"]
    assert client.get("/api/harness/v1/experiments").json()[0]["current_revision_id"] == revision["id"]
    assert revision["digest"].startswith("sha256:")
    assert client.get(f"/api/harness/v1/experiment-revisions/{revision['id']}").json() == revision
    validation = client.post(f"/api/harness/v1/experiment-revisions/{revision['id']}/validate").json()
    assert validation["ok"] and validation["execution_authorized"] is False

    next_protocol = protocol(design, "Does an independent trial reproduce the result?")
    next_protocol["trials"][0].update(key="independent-1", purpose="independent_replication")
    response = client.post(
        f"/api/harness/v1/experiments/{experiment['id']}/revisions",
        json={"base_id": revision["id"], **next_protocol},
    )
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["revision"] == 2 and second["trials"][0]["id"] != revision["trials"][0]["id"]
    assert client.post(
        f"/api/harness/v1/experiments/{experiment['id']}/revisions",
        json={"base_id": revision["id"], **next_protocol},
    ).status_code == 409
    current = client.get(f"/api/harness/v1/experiments/{experiment['id']}").json()
    assert current["current_revision"] == 2 and current["current_revision_id"] == second["id"]
    client.app.state.workers.stop()
    restarted = create_app(tmp_path)
    client.app = restarted
    restored = restarted.state.harness.get_experiment(experiment["id"])
    assert restored["current_revision"] == 2 and restored["current_revision_id"] == second["id"]
    assert restarted.state.harness.get_revision(second["id"]) == second


def test_asset_references_use_authoritative_design_and_run_documents(client, tmp_path):
    design_ids, run_ids = seed_assets(tmp_path)
    design = client.get(f"/api/harness/v1/assets/design/{design_ids[0]}/reference")
    assert design.status_code == 200 and design.json() == design_ref(saved_design(tmp_path, design_ids[0]))
    run = client.get(f"/api/harness/v1/assets/run/{run_ids[0]}/reference").json()
    saved_run = json.loads((tmp_path / "runs" / run_ids[0] / "run.json").read_text())
    assert run == {"kind": "run", "id": run_ids[0], "digest": content_hash(saved_run)}
    assert client.get(f"/api/harness/v1/assets/unknown/{run_ids[0]}/reference").status_code == 422
    assert client.get(f"/api/harness/v1/assets/run/{design_ids[0]}/reference").status_code == 422


def test_experiment_rejects_missing_and_mismatched_references(client, tmp_path):
    design_ids, _ = seed_assets(tmp_path)
    design = saved_design(tmp_path, design_ids[0])
    payload = {"title": "Bad reference", **protocol(design)}
    payload["inputs"]["design"]["id"] = legacy_ulid("design", "missing")
    response = client.post("/api/harness/v1/experiments", json=payload)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "retryable", "request_id"}
    payload = {"title": "Bad digest", **protocol(design)}
    payload["inputs"]["design"]["digest"] = "sha256:" + "0" * 64
    assert client.post("/api/harness/v1/experiments", json=payload).status_code == 409


def test_dataset_snapshot_from_real_npz_and_authoritative_lineage(client, tmp_path):
    design_ids, run_ids = seed_assets(tmp_path)
    payload = snapshot_payload(run_ids, [{"group_id": design_ids[0], "split": "train"}, {"group_id": design_ids[1], "split": "test"}])
    response = client.post("/api/harness/v1/dataset-snapshots", json=payload)
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert snapshot["total_samples"] == 9
    assert client.post(f"/api/harness/v1/dataset-snapshots/{snapshot['id']}/validate").json()["ok"]
    edges = client.get(f"/api/harness/v1/assets/{run_ids[0]}/lineage").json()["edges"]
    assert any(edge["child_id"] == snapshot["id"] and edge["relation"] == "contains_episode" for edge in edges)
    _reindex(client.app.state.store, tmp_path)
    assert client.get(f"/api/harness/v1/assets/{run_ids[0]}/lineage").json()["edges"] == edges
    client.app.state.workers.stop()
    restarted = create_app(tmp_path)
    client.app = restarted
    assert restarted.state.harness.get_snapshot(snapshot["id"]) == snapshot


def test_snapshot_rejects_leakage_unknown_group_missing_channel_and_path_escape(client, tmp_path):
    design_ids, run_ids = seed_assets(tmp_path)
    base = [{"group_id": design_ids[0], "split": "train"}, {"group_id": design_ids[1], "split": "test"}]
    leaking = snapshot_payload(run_ids, [*base, {"group_id": design_ids[0], "split": "test"}])
    assert client.post("/api/harness/v1/dataset-snapshots", json=leaking).status_code == 422
    unknown = snapshot_payload(run_ids, [base[0], {"group_id": legacy_ulid("design", "unknown"), "split": "test"}])
    assert client.post("/api/harness/v1/dataset-snapshots", json=unknown).status_code == 422
    missing_channel = snapshot_payload(run_ids, base)
    missing_channel["observation"]["channels"] = ["t", "absent"]
    response = client.post("/api/harness/v1/dataset-snapshots", json=missing_channel)
    assert response.status_code == 422 and "absent" in response.json()["message"]
    escaping = snapshot_payload(run_ids, base)
    escaping["sources"][0]["arrays_file"] = "../arrays.npz"
    assert client.post("/api/harness/v1/dataset-snapshots", json=escaping).status_code == 422
    unequal = snapshot_payload(run_ids, base)
    unequal["observation"]["channels"] = ["t"]
    run_path = tmp_path / "runs" / run_ids[0] / "arrays.npz"
    np.savez(run_path, t=np.arange(4), psi=np.arange(3))
    assert client.post("/api/harness/v1/dataset-snapshots", json=unequal).status_code == 201


def test_snapshot_validation_detects_run_and_array_tampering(client, tmp_path):
    design_ids, run_ids = seed_assets(tmp_path)
    payload = snapshot_payload(run_ids, [{"group_id": design_ids[0], "split": "train"}, {"group_id": design_ids[1], "split": "test"}])
    snapshot = client.post("/api/harness/v1/dataset-snapshots", json=payload).json()
    arrays_path = tmp_path / "runs" / run_ids[0] / "arrays.npz"
    original = arrays_path.read_bytes()
    np.savez(arrays_path, t=np.arange(4), psi=np.zeros(4))
    response = client.post(f"/api/harness/v1/dataset-snapshots/{snapshot['id']}/validate")
    assert response.status_code == 409 and response.json()["code"] == "snapshot_source_changed"
    arrays_path.write_bytes(original)
    run_path = tmp_path / "runs" / run_ids[0] / "run.json"
    run = json.loads(run_path.read_text())
    run["metrics"]["stride_per_rev"] = 99
    run_path.write_text(json.dumps(run))
    assert client.post(f"/api/harness/v1/dataset-snapshots/{snapshot['id']}/validate").status_code == 409


def test_unsupported_transforms_and_unknown_harness_assets_are_explicit(client):
    response = client.post("/api/harness/v1/dataset-snapshots", json={"transforms": [{"kind": "standardize"}]})
    assert response.status_code == 422 and "transforms" in response.json()["message"]
    assert client.get("/api/harness/v1/experiments/unknown").status_code == 404
    assert client.get("/api/harness/v1/dataset-snapshots/unknown").status_code == 404
