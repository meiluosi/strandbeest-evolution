"""Persisted API scenarios must be valid executable inputs, including explicit nulls."""

import copy
import json

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_api.pipeline import compute_run_key
from strandbeest_sim import load_scenario, run, scenario_from_design
from strandbeest_sim.config import sim_config
from strandbeest_sim.events import nominal_stride_m

from test_cache_identity import DESIGN, OVERRIDES, client_at, run_job


@pytest.mark.parametrize("stiffness", [300000.0, None])
def test_saved_api_scenario_is_valid_and_replays_identically_after_restart(tmp_path, stiffness):
    overrides = copy.deepcopy(OVERRIDES)
    overrides["solver"] = {"contact_stiffness": stiffness}
    payload = {"design": DESIGN, "ensemble": False, "overrides": overrides}
    with client_at(tmp_path) as client:
        produced = run_job(client, payload)
    path = tmp_path / "runs" / produced["id"] / "run.json"
    original = path.read_bytes()
    with client_at(tmp_path) as client:
        stored = client.get(f"/runs/{produced['id']}").json()
        assert stored == json.loads(original)
        document = stored["scenario"]
        schema = json.loads((schema_dir() / "scenario.schema.json").read_text())
        Draft202012Validator(schema).validate(document)
        assert "pneumatics" not in document["entities"][0]["components"]
        assert "contact_stiffness" in document["solver"]
        assert document["solver"]["contact_stiffness"] == stiffness
        reloaded = load_scenario(document)
        assert reloaded == scenario_from_design(Design(DESIGN), overrides)
        replay = run(reloaded)
        with np.load(path.parent / "arrays.npz") as arrays:
            for key in ("t", "psi", "x", "z", "torque"):
                np.testing.assert_array_equal(getattr(replay, key), arrays[key])
        assert compute_run_key(Design(DESIGN), overrides)["key"] == produced["provenance"]["input_key"]
        cached = run_job(client, payload)
        assert cached["provenance"]["cache_hit_from"] == produced["id"]
    assert path.read_bytes() == original


@pytest.mark.parametrize("named", [False, True])
def test_replay_stride_reference_uses_the_executed_geometry_and_overrides(tmp_path, named):
    overrides = copy.deepcopy(OVERRIDES)
    overrides["run"].update(max_time=.1, frame_rate=30)
    overrides["linkage"] = {"params": {"a": DESIGN["linkage"]["params"]["a"] * 1.01}}
    if named:
        overrides["linkage"]["spec"] = "jansen"
    with client_at(tmp_path) as client:
        produced = run_job(client, {"design": DESIGN, "ensemble": False, "overrides": overrides})
        response = client.get(f"/runs/{produced['id']}/replay")
        assert response.status_code == 200, response.text
        replay = response.json()
    expected = nominal_stride_m(sim_config(load_scenario(produced["scenario"])))
    baseline = nominal_stride_m(sim_config(scenario_from_design(Design(DESIGN))))
    assert expected != baseline
    assert replay["nominal_stride_m"] == expected
    assert replay["kinematic_duty"] is not None
