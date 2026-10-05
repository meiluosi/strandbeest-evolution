import json
import time

import pytest
from fastapi.testclient import TestClient

from strandbeest_api import create_app
from strandbeest_common.schemas import schema_dir

DESIGN = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path))


def test_validate_reports_errors_and_accepts_good_designs(client):
    assert client.post("/designs/validate", json=DESIGN).json()["ok"] is True
    bad = {**DESIGN, "extra": 1}
    r = client.post("/designs/validate", json=bad).json()
    assert r["ok"] is False and any("extra" in e for e in r["errors"])


def test_save_and_list_designs(client):
    assert client.post("/designs", json=DESIGN).status_code == 200
    assert DESIGN["name"] in client.get("/designs").json()
    assert client.get(f"/designs/{DESIGN['name']}").json()["name"] == DESIGN["name"]
    assert client.post("/designs", json={**DESIGN, "extra": 1}).status_code == 422


def test_evaluate_returns_a_d_shaped_gait(client):
    g = client.post("/evaluate", json=DESIGN).json()["gait"]
    assert g["assembled"] and 0.3 < g["duty"] < 0.6


def test_export_returns_checks_and_a_downloadable_zip(client):
    r = client.post("/exports", json=DESIGN).json()
    assert r["parts"] == 18 and not [c for c in r["checks"] if c["status"] == "fail"]
    z = client.get(r["download"])
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip" and z.content[:2] == b"PK"


def test_run_job_completes_and_series_are_served(client):
    jid = client.post("/runs", json={"design": DESIGN, "overrides": {"run": {"revolutions": 0.4, "settle": 0.2}}}).json()["job_id"]
    for _ in range(300):
        j = client.get(f"/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j
    rid = j["result"]["id"]
    assert client.get(f"/runs/{rid}").json()["design_name"] == DESIGN["name"]
    s = client.get(f"/runs/{rid}/series").json()
    assert set(s) >= {"t", "psi", "torque"} and len(s["t"]) > 3


def test_unknown_things_are_404(client):
    assert client.get("/jobs/nope").status_code == 404
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/designs/nope").status_code == 404


def test_ensemble_run_reports_ranges_and_marks_invalid_variants(client):
    jid = client.post("/runs", json={"design": DESIGN, "ensemble": True, "overrides": {"run": {"revolutions": 0.8, "settle": 0.3}}}).json()["job_id"]
    for _ in range(400):
        j = client.get(f"/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j
    ens = j["result"]["ensemble"]
    assert len(ens["variants"]) == 4 and ens["variants"][0]["valid"] is not None
    for key, (lo, hi) in ens["ranges"].items():
        assert lo <= hi, key
    # ranges only use valid variants
    valid_stride = [v["metrics"]["stride_per_rev"] for v in ens["variants"] if v["valid"]]
    assert ens["ranges"]["stride_per_rev"] == [min(valid_stride), max(valid_stride)]


MEAS = {
    "schema_version": 1, "id": "m1", "design_name": "jansen-small-6leg", "synthetic": False,
    "conditions": {"kind": "motor_no_wind", "omega_rad_s": 2.0},
    "channels": {"t": [i * 0.05 for i in range(400)], "psi": [i * 0.1 for i in range(400)], "torque": [0.02 + 0.01 * ((i % 63) / 63) for i in range(400)]},
}


def test_measurements_can_be_saved_listed_and_validated(client):
    assert client.post("/measurements", json=MEAS).status_code == 200
    assert client.get("/measurements").json()[0]["id"] == "m1"
    assert client.get("/measurements/m1").json()["channels"]["t"][1] == 0.05
    assert client.post("/measurements", json={**MEAS, "extra": 1}).status_code == 422


def test_runs_are_listed_and_compared_with_a_measurement(client):
    jid = client.post("/runs", json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 1.2, "settle": 0.3}}}).json()["job_id"]
    for _ in range(300):
        j = client.get(f"/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j
    rid = j["result"]["id"]
    assert client.get("/runs").json()[0]["id"] == rid
    cmp = client.post("/compare", json={"measurement": MEAS, "run_id": rid}).json()
    assert len(cmp["angle_deg"]) == len(cmp["measured"]) == len(cmp["simulated"])
    assert cmp["distance"] is not None
    assert client.get(f"/runs/{rid}/series").status_code == 200


def test_export_parts_endpoint_serves_outlines(client):
    e = client.post("/exports", json=DESIGN).json()
    parts = client.get(f"/exports/{e['export_id']}/parts").json()["parts"]
    assert "frame_plate" in parts and parts["frame_plate"]["outline"]["exterior"]


def test_calibration_rejects_unknown_parameters(client):
    r = client.post("/calibrations", json={"design": DESIGN, "measurement": MEAS, "params": ["nope"]})
    assert r.status_code == 422
