"""Record a real native/API replay of original G1 case 11 (absorbed net work).

Only frame recording is enabled; the original physical inputs are unchanged.
Old corpus files are never replaced. Run from the repository root with output
fixture and a fresh temporary API data directory as positional arguments.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from strandbeest_api.app import create_app
from strandbeest_api.pipeline import simulate
from strandbeest_common import Design

ROOT = Path(__file__).resolve().parents[3]


def main():
    output, storage = map(Path, sys.argv[1:])
    if output.exists() or storage.exists():
        raise FileExistsError("Fixture and data directory must both be new")
    source = ROOT / "experiments/hardening-g1-contact-v3-default-2026-11-04.json"
    row = next(r for r in json.loads(source.read_text())["rows"] if r["case"] == 11)
    overrides = copy.deepcopy(row["overrides"])
    overrides["run"]["frame_rate"] = 30
    storage.mkdir(parents=True)
    document = simulate(Design(row["design"]), storage / "runs", overrides)
    for key, value in row["metrics"].items():
        assert document["metrics"][key] == value, key
    assert document["metrics"]["energy_in_per_rev"] < 0
    assert abs(document["metrics"]["energy_residual_share"]) < .02
    app = create_app(storage, workers=0)
    try:
        with TestClient(app) as client:
            response = client.get(f"/runs/{document['id']}/replay")
            assert response.status_code == 200, response.text
            replay = response.json()
    finally:
        app.state.workers.stop()
        app.state.store._db.close()
    assert replay["metrics"] == document["metrics"]
    arrays_path = storage / "runs" / document["id"] / "arrays.npz"
    with np.load(arrays_path) as arrays:
        series = {key: arrays[key].tolist() for key in ["t", "psi", "x", "z", "torque",
                  "e_in", "e_contact", "e_loops", "e_friction", "kinetic", "potential"]}
    result = {"source": str(source.relative_to(ROOT)),
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "case": 11, "physical_inputs_changed": False,
              "recording_override": {"run.frame_rate": 30},
              "original_metrics_unchanged": True, "design": row["design"],
              "overrides": overrides, "scenario": document["scenario"],
              "provenance": document["provenance"], "raw_series": series, "replay": replay,
              "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with output.open("x") as f:
        json.dump(result, f, separators=(",", ":"), allow_nan=False)
        f.write("\n")
    print(json.dumps({"output": str(output), "bytes": output.stat().st_size,
                      "run_id": document["id"], "metrics": replay["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
