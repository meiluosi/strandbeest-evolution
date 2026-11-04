"""H1-06 controlled cache-identity probe, using only a TemporaryDirectory.

Run from the repository with its installed Python environment:
    .venv/bin/python apps/api/scripts/hardening_cache_identity.py --expect-stale --output RESULT.json

Both computations execute the real MuJoCo simulator. An in-process observation
wrapper then adds a TEST-ONLY revision marker (1 or 2); those numbers are not
energy, torque, error, or any other physical quantity. The second application
starts against the same temporary files, exercising normal startup reindexing.
No production function or user data file is edited. This is a baseline diagnostic,
not a substitute for tests of actual implementation fingerprint changes. The
--expect-fixed mode checks fail-closed handling of runtime-injected observers;
test_cache_process.py separately exercises real file changes and OS processes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir

import strandbeest_api.pipeline as pipeline
from strandbeest_api.app import create_app

REPOSITORY = Path(__file__).resolve().parents[3]
PROBE_METRIC = "test_only_observation_revision"
SOURCE_FILES = (
    "apps/api/scripts/hardening_cache_identity.py",
    "apps/api/src/strandbeest_api/app.py",
    "apps/api/src/strandbeest_api/pipeline.py",
    "apps/api/src/strandbeest_api/jobs.py",
    "packages/common/src/strandbeest_common/hashing.py",
    "packages/common/src/strandbeest_common/migrate.py",
    "packages/sim/src/strandbeest_sim/runner.py",
    "packages/sim/src/strandbeest_sim/builder.py",
    "packages/sim/src/strandbeest_sim/backends/mujoco_backend.py",
    "schemas/run.schema.json",
)


def _invoke(client: TestClient, payload: dict) -> dict:
    response = client.post("/runs", json=payload)
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{job_id}").json()
        if status["status"] in ("done", "failed"):
            assert status["status"] == "done", status
            return status["result"]
        time.sleep(0.01)
    raise AssertionError("isolated job timed out")


def _close(app) -> None:
    app.state.workers.stop()
    for thread in app.state.workers._threads:
        thread.join(1)
        assert not thread.is_alive(), "worker did not stop before temporary-directory cleanup"
    app.state.store._db.close()


def probe() -> dict:
    original = pipeline.sim_run
    calls = {"old": 0, "new": 0}

    def algorithm(label: str, marker: float):
        def run(scenario):
            calls[label] += 1
            result = original(scenario)
            result.metrics[PROBE_METRIC] = marker
            return result
        return run

    design = json.loads((schema_dir() / "examples/design-jansen-small-6leg.json").read_text())
    design["walker"]["legs"] = 2
    payload = {
        "design": design,
        "ensemble": False,
        "overrides": {
            "run": {"settle": 0.02, "max_time": 0.1, "revolutions": 2, "frame_rate": 0},
            "drive": {"omega": 4, "ramp": 0.03},
        },
    }
    with tempfile.TemporaryDirectory(prefix="beest-cache-semantic-") as temporary:
        root = Path(temporary)
        with patch.dict(os.environ, {"STRANDBEEST_CODE_VERSION": "probe-old-observer"}), \
                patch.object(pipeline, "sim_run", algorithm("old", 1.0)):
            old_key = pipeline.compute_run_key(Design(design), payload["overrides"])
            first_app = create_app(root, workers=1)
            try:
                with TestClient(first_app) as client:
                    old = _invoke(client, payload)
            finally:
                _close(first_app)
        old_path = root / "runs" / old["id"] / "run.json"
        old_bytes = old_path.read_bytes()
        with patch.dict(os.environ, {"STRANDBEEST_CODE_VERSION": "probe-new-observer"}), \
                patch.object(pipeline, "sim_run", algorithm("new", 2.0)):
            new_key = pipeline.compute_run_key(Design(design), payload["overrides"])
            second_app = create_app(root, workers=1)
            try:
                with TestClient(second_app) as client:
                    cached = _invoke(client, payload)
                    new_calls_at_hit = calls["new"]
                    fresh = _invoke(client, {**payload, "use_cache": False})
            finally:
                _close(second_app)
        result = {
            "review_date": "2026-11-04",
            "kind": "controlled_observation_algorithm_probe_not_physical_measurement",
            "probe_metric": {"name": PROBE_METRIC, "meaning": "Test-only observer revision marker; 1 and 2 have no physical interpretation."},
            "runtime": {"mujoco_version": pipeline.mujoco.__version__, "python": platform.python_version(),
                        "platform": platform.system().lower() + "-" + platform.machine().lower()},
            "isolation": {"storage": "TemporaryDirectory", "repository_data_accessed": False,
                          "temporary_path": temporary, "worker_process_restart": False,
                          "application_recreated_and_startup_reindex_executed": True,
                          "note": "Both application lifecycles run sequentially in this diagnostic process; workers are stopped/joined and SQLite connections closed between them."},
            "input": payload,
            "keys_equal_across_controlled_algorithm_and_application_version_change": old_key == new_key,
            "old_key": old_key,
            "new_key": new_key,
            "after_restart_cache_hit_from_old": cached["provenance"].get("cache_hit_from") == old["id"],
            "cached_code_version": cached["provenance"]["code_version"],
            "new_algorithm_calls_at_cache_hit": new_calls_at_hit,
            "probe_values": {"old": old["metrics"][PROBE_METRIC], "cached": cached["metrics"][PROBE_METRIC],
                             "forced_fresh": fresh["metrics"][PROBE_METRIC]},
            "forced_fresh_code_version": fresh["provenance"]["code_version"],
            "forced_fresh_uses_same_input_key": bool(fresh["provenance"].get("input_key")) and fresh["provenance"].get("input_key") == old["provenance"].get("input_key"),
            "execution_identity": fresh["provenance"].get("execution_identity"),
            "run_ids": {"old": old["id"], "cached": cached["id"], "forced_fresh": fresh["id"]},
            "old_record_unchanged": old_path.read_bytes() == old_bytes,
            "native_calls": calls,
            "source_sha256": {name: hashlib.sha256((REPOSITORY / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        }
        assert result["old_record_unchanged"]
        assert result["probe_values"]["forced_fresh"] == 2
    result["isolation"]["temporary_directory_removed"] = not root.exists()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    expectations = parser.add_mutually_exclusive_group()
    expectations.add_argument("--expect-stale", action="store_true", help="assert the historical defect; omit for diagnostic comparison")
    expectations.add_argument("--expect-fixed", action="store_true", help="assert injected observers cannot reuse the old result")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error(f"refusing to overwrite evidence: {args.output}")
    result = probe()
    if args.expect_stale:
        assert result["keys_equal_across_controlled_algorithm_and_application_version_change"]
        assert result["after_restart_cache_hit_from_old"]
        assert result["new_algorithm_calls_at_cache_hit"] == 0
        assert result["probe_values"]["cached"] == 1
    if args.expect_fixed:
        assert not result["after_restart_cache_hit_from_old"]
        assert result["new_algorithm_calls_at_cache_hit"] == 1
        assert result["probe_values"]["cached"] == 2
        assert result["execution_identity"]["status"] == "unavailable"
        assert result["execution_identity"]["reason"] == "runtime_bindings_changed"
    text = json.dumps(result, ensure_ascii=False, indent="\t") + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(json.dumps({key: result[key] for key in ("kind", "after_restart_cache_hit_from_old", "new_algorithm_calls_at_cache_hit", "probe_values", "native_calls")}, indent=2))


if __name__ == "__main__":
    main()
