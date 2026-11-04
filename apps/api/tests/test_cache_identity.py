"""H1-06: real simulation/cache/reindex tests, with all storage isolated."""

import copy
import json
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from strandbeest_api import create_app
from strandbeest_api import execution
from strandbeest_api.pipeline import cache_matches, compute_run_key, simulate
from strandbeest_common import Design
from strandbeest_common.implementation import ProcessImplementation, unavailable_identity
from strandbeest_common.migrate import migrate_doc
from strandbeest_common.schemas import schema_dir, validate

DESIGN = json.loads((schema_dir() / "examples/design-jansen-small-6leg.json").read_text())
DESIGN["walker"]["legs"] = 2
OVERRIDES = {"run": {"settle": 0, "max_time": 0.03, "revolutions": 2, "frame_rate": 0},
             "drive": {"omega": 4, "ramp": 0.01}}
PAYLOAD = {"design": DESIGN, "ensemble": False, "overrides": OVERRIDES}


@contextmanager
def client_at(root):
    app = create_app(root, workers=1)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.state.workers.stop()
        for thread in app.state.workers._threads:
            thread.join(2)
            assert not thread.is_alive()
        app.state.store._db.close()


def run_job(client, payload=PAYLOAD):
    response = client.post("/runs", json=payload)
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{response.json()['job_id']}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            assert job["status"] == "done", job
            return job["result"]
        time.sleep(0.01)
    raise AssertionError("isolated run job timed out")


def test_same_implementation_hits_after_restart_but_forced_run_recomputes(tmp_path):
    with client_at(tmp_path) as client:
        first = run_job(client)
    path = tmp_path / "runs" / first["id"] / "run.json"
    original = path.read_bytes()
    identity = first["provenance"]["execution_identity"]
    assert identity["status"] == "verified"
    assert any(name.endswith(".so") or name.endswith(".pyd") for name in identity["manifest"]["files"])
    assert identity["manifest"]["runtime"]["mujoco"] == first["provenance"]["engine_version"]
    with client_at(tmp_path) as client:
        hit = run_job(client)
        fresh = run_job(client, {**PAYLOAD, "use_cache": False})
        assert hit["id"] == hit["provenance"]["cache_hit_from"] == first["id"]
        assert fresh["id"] != first["id"] and "cache_hit_from" not in fresh["provenance"]
        assert first["metrics"] == hit["metrics"] == fresh["metrics"]
        assert fresh["provenance"]["input_key"] == first["provenance"]["input_key"]
    assert path.read_bytes() == original


@pytest.mark.parametrize("legacy_version", [1, 2])
def test_reindex_never_backfills_identity_or_reuses_legacy_even_with_matching_key(tmp_path, legacy_version):
    first = simulate(Design(DESIGN), tmp_path / "runs", OVERRIDES)
    path = tmp_path / "runs" / first["id"] / "run.json"
    # Deliberately give the legacy row a CURRENT key: lookup must check the Run,
    # not merely rely on v1/v2 hashes normally being different.
    del first["provenance"]["execution_identity"]
    if legacy_version == 1:
        first["schema_version"] = 1
        del first["design_id"]
    path.write_text(json.dumps(first, indent=2))
    before = path.read_bytes()
    with client_at(tmp_path) as client:
        historical = client.get(f"/runs/{first['id']}")
        assert historical.status_code == 200
        assert "execution_identity" not in historical.json()["provenance"]
        new = run_job(client)
        assert new["id"] != first["id"] and "cache_hit_from" not in new["provenance"]
        assert new["provenance"]["execution_identity"]["status"] == "verified"
    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("engine_version", "a different backend"),
    ("design_hash", "sha256:" + "f" * 64),
    ("platform", "another-platform"),
    ("seed", 1),
    ("execution_identity", {}),
])
def test_matching_index_key_is_not_enough_to_reuse_a_record(tmp_path, field, value):
    doc = simulate(Design(DESIGN), tmp_path, OVERRIDES)
    key = compute_run_key(Design(DESIGN), OVERRIDES)
    assert cache_matches(doc, key, ensemble=False)
    assert not cache_matches(doc, key, ensemble=True)
    doc["provenance"][field] = value
    assert not cache_matches(doc, key, ensemble=False)


def test_unavailable_identity_still_simulates_and_never_uses_or_writes_cache_key(tmp_path, monkeypatch):
    with client_at(tmp_path) as client:
        first = run_job(client)
        missing = tmp_path / "absent-implementation.py"
        unknown = ProcessImplementation(lambda: {"missing.py": missing}, lambda: {})
        monkeypatch.setattr(execution, "PROCESS_IMPLEMENTATION", unknown)
        for _ in range(2):
            result = run_job(client)
            assert result["id"] != first["id"]
            assert "input_key" not in result["provenance"]
            assert "cache_hit_from" not in result["provenance"]
            assert result["provenance"]["execution_identity"]["reason"] == "implementation_unavailable"
            validate("run", result)


def test_change_during_execution_removes_cache_identity(tmp_path, monkeypatch):
    before = execution.execution_identity()
    assert before["status"] == "verified"

    class ChangingImplementation:
        calls = 0

        def current(self):
            self.calls += 1
            return before if self.calls == 1 else unavailable_identity("implementation_changed_since_import")

    monkeypatch.setattr(execution, "PROCESS_IMPLEMENTATION", ChangingImplementation())
    doc = simulate(Design(DESIGN), tmp_path, OVERRIDES)
    assert "input_key" not in doc["provenance"]
    assert doc["provenance"]["execution_identity"]["reason"] == "implementation_changed_during_run"
    validate("run", doc)


def test_runtime_observer_changes_disable_cache_without_relabeling_old_result(tmp_path, monkeypatch):
    import strandbeest_api.pipeline as pipeline

    with client_at(tmp_path) as client:
        first = run_job(client)
        original = pipeline.sim_run

        def changed(scenario):
            result = original(scenario)
            result.metrics["test_only_revision"] = 2
            return result

        monkeypatch.setattr(pipeline, "sim_run", changed)
        result = run_job(client)
        assert result["id"] != first["id"]
        assert result["metrics"]["test_only_revision"] == 2
        assert result["provenance"]["execution_identity"]["reason"] == "runtime_bindings_changed"
        assert "input_key" not in result["provenance"]


def test_schema_roundtrip_preserves_identity_and_migration_does_not_invent_it(tmp_path):
    new = simulate(Design(DESIGN), tmp_path, OVERRIDES)
    validate("run", new)
    assert migrate_doc("run", json.loads(json.dumps(new))) == new
    old = json.loads((schema_dir() / "examples/run-example.json").read_text())
    unchanged = copy.deepcopy(old)
    assert migrate_doc("run", old) == unchanged == old
    assert "execution_identity" not in old["provenance"]
    # A claimed verified identity needs an actual manifest and hash.
    malformed = copy.deepcopy(new)
    del malformed["provenance"]["execution_identity"]["implementation_hash"]
    with pytest.raises(ValueError, match="invalid run"):
        validate("run", malformed)
