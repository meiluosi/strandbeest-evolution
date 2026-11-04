"""Actual Measurement -> calibration -> executable Profile -> Run provenance."""

import copy
import json
import time

import numpy as np
import pytest

from strandbeest_common import Design
from strandbeest_common.ids import new_ulid
from strandbeest_common.migrate import migrate_doc
from strandbeest_common.schemas import schema_dir, validate
from strandbeest_sim import run, scenario_from_design
from strandbeest_calib.calibrate import parameter_overrides

from test_cache_identity import DESIGN, OVERRIDES, client_at, run_job


@pytest.fixture(scope="module")
def measurement():
    design = Design(DESIGN)
    result = run(scenario_from_design(design, {"run": {"revolutions": 1.1, "settle": 0.1, "frame_rate": 0}}))
    doc = {"schema_version": 2, "id": new_ulid(), "name": "synthetic-source-for-api-test",
           "design_id": design.id, "synthetic": True,
           "conditions": {"kind": "motor_no_wind", "omega_rad_s": 2.0},
           "channels": {"t": result.t.tolist(), "psi": result.psi.tolist(), "torque": result.torque.tolist(), "x": result.x.tolist()},
           "provenance": {"source": "simulator", "raw_file": "synthetic-test-only.json",
                          "calibration": {"generator": "native MuJoCo test fixture", "units": {"torque": "N·m"}}}}
    validate("measurement", doc)
    assert np.isfinite(result.torque).all()
    return doc


def calibrate_job(client, doc, params=None):
    response = client.post("/calibrations", json={"design": DESIGN, "measurement": doc,
                           "params": params or ["contact_stiffness"], "max_evals": 1})
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{response.json()['job_id']}").json()
        if job["status"] in ("done", "failed"):
            assert job["status"] == "done", job
            return job["result"]
        time.sleep(.01)
    raise AssertionError("calibration timed out")


def test_inline_measurement_persists_and_applied_profile_is_traceable_after_restart(tmp_path, measurement):
    with client_at(tmp_path) as client:
        profile = calibrate_job(client, measurement)
        assert client.get(f"/measurements/{measurement['id']}").json() == measurement
        assert profile["provenance"]["measurement_ids"] == [measurement["id"]]
        assert profile["provenance"]["synthetic"] is True
        assert profile["provenance"]["parameter_mapping_version"] == "beest-physical-v2"
        assert "scenario" in profile
        # Same physical parameters alone do not authorize relabeling a cached
        # Run as if a different calibration had produced it.
        flat = parameter_overrides(profile["parameters"], Design(DESIGN))
        flat.update(OVERRIDES)
        plain = run_job(client, {"design": DESIGN, "ensemble": False, "overrides": flat})
        applied = run_job(client, {"design": DESIGN, "ensemble": False, "overrides": OVERRIDES, "profile_id": profile["id"]})
        assert applied["id"] != plain["id"]
        assert "cache_hit_from" not in applied["provenance"]
        assert applied["provenance"]["calibration_profile_id"] == profile["id"]
        assert applied["scenario"]["solver"]["contact_stiffness"] == profile["parameters"]["contact_stiffness"]
        validate("run", applied)
    original = (tmp_path / "measurements" / f"{measurement['id']}.json").read_bytes()
    with client_at(tmp_path) as client:
        again = run_job(client, {"design": DESIGN, "ensemble": False, "overrides": OVERRIDES, "profile_id": profile["id"]})
        assert again["provenance"]["cache_hit_from"] == applied["id"]
        graph = client.get(f"/runs/{applied['id']}/provenance").json()
        assert graph["profiles"][0]["id"] == profile["id"]
        assert graph["measurements"][0]["id"] == measurement["id"]
        assert graph["measurements"][0]["synthetic"] is True
        assert client.get(f"/profiles/{profile['id']}/provenance").json()["measurements"][0]["id"] == measurement["id"]
    assert (tmp_path / "measurements" / f"{measurement['id']}.json").read_bytes() == original


def test_leg_mass_is_supported_by_both_calibrators_and_can_be_applied(tmp_path, measurement):
    with client_at(tmp_path) as client:
        profile = calibrate_job(client, measurement, ["leg_mass_per_m"])
        applied = run_job(client, {"design": DESIGN, "ensemble": False, "overrides": OVERRIDES, "profile_id": profile["id"]})
        body = applied["scenario"]["entities"][0]["components"]["body"]
        assert body["tube_mass_per_m"] == profile["parameters"]["leg_mass_per_m"]


def test_profile_design_mutation_missing_source_and_unknown_parameters_fail_before_queueing(tmp_path, measurement):
    with client_at(tmp_path) as client:
        profile = calibrate_job(client, measurement)
        path = tmp_path / "profiles" / f"{profile['id']}.json"
        payload = {"design": DESIGN, "profile_id": profile["id"], "ensemble": False}
        before = len(client.get("/jobs").json())
        changed = copy.deepcopy(DESIGN)
        changed["walker"]["body_mass_kg"] *= 2
        response = client.post("/runs", json={**payload, "design": changed})
        assert response.status_code == 422 and response.json()["detail"]["code"] == "calibration_profile_invalid"
        for change in ("unknown", "mapping_missing", "mapping_previous", "missing_measurement", "synthetic_mismatch"):
            bad = copy.deepcopy(profile)
            if change == "unknown": bad["parameters"] = {"k_flex": .002}
            elif change == "mapping_missing": bad["provenance"].pop("parameter_mapping_version")
            elif change == "mapping_previous": bad["provenance"]["parameter_mapping_version"] = "beest-physical-v1"
            elif change == "missing_measurement": bad["provenance"]["measurement_ids"] = [new_ulid()]
            else: bad["provenance"]["synthetic"] = False
            path.write_text(json.dumps(bad))
            original = path.read_bytes()
            assert client.get(f"/profiles/{profile['id']}").json() == bad
            assert client.post("/runs", json=payload).status_code == 422
            assert path.read_bytes() == original
        assert len(client.get("/jobs").json()) == before


def test_evidence_cannot_be_overwritten_through_upload_or_inline_calibration(tmp_path, measurement):
    with client_at(tmp_path) as client:
        assert client.post("/measurements", json=measurement).status_code == 200
        original = (tmp_path / "measurements" / f"{measurement['id']}.json").read_bytes()
        changed = copy.deepcopy(measurement)
        changed["synthetic"] = False
        for endpoint, payload in [("/measurements", changed),
                                  ("/calibrations", {"design": DESIGN, "measurement": changed, "max_evals": 1})]:
            response = client.post(endpoint, json=payload)
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "measurement_id_conflict"
        assert (tmp_path / "measurements" / f"{measurement['id']}.json").read_bytes() == original


def test_legacy_profile_roundtrip_preserves_original_units_without_invented_mapping():
    old = json.loads((schema_dir() / "examples/profile-example.json").read_text())
    assert migrate_doc("profile", json.loads(json.dumps(old))) == old
    assert "parameter_mapping_version" not in old["provenance"]
    assert "scenario" not in old


def test_unstated_calibration_conditions_fail_before_a_job_is_created(tmp_path, measurement):
    with client_at(tmp_path) as client:
        incomplete = copy.deepcopy(measurement)
        incomplete["conditions"].pop("omega_rad_s")
        for endpoint in ("/calibrations", "/calibrations/bayes"):
            response = client.post(endpoint, json={"design": DESIGN, "measurement": incomplete})
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == "calibration_measurement_invalid"
        assert client.get("/jobs").json() == []
