import json
import time

import pytest
from fastapi.testclient import TestClient

from strandbeest_api import create_app
from strandbeest_common.schemas import schema_dir

DESIGN = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    yield TestClient(app)
    app.state.workers.stop()


def wait(client, jid, tries=400):
    for _ in range(tries):
        j = client.get(f"/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.25)
    return j


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


MEAS_ID = "01K0000000000000000000000M"
MEAS = {
    "schema_version": 2, "id": MEAS_ID, "name": "m1", "design_id": DESIGN["id"], "design_name": "jansen-small-6leg", "synthetic": False,
    "conditions": {"kind": "motor_no_wind", "omega_rad_s": 2.0},
    "channels": {"t": [i * 0.05 for i in range(400)], "psi": [i * 0.1 for i in range(400)], "torque": [0.02 + 0.01 * ((i % 63) / 63) for i in range(400)]},
}


def test_measurements_can_be_saved_listed_and_validated(client):
    assert client.post("/measurements", json=MEAS).status_code == 200
    listed = client.get("/measurements").json()[0]
    assert listed["id"] == MEAS_ID and listed["name"] == "m1" and listed["design_id"] == DESIGN["id"]
    assert client.get(f"/measurements/{MEAS_ID}").json()["channels"]["t"][1] == 0.05
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


def test_jobs_report_progress_kind_and_are_listed(client):
    jid = client.post("/runs", json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.4, "settle": 0.2}}}).json()["job_id"]
    j = wait(client, jid)
    assert j["status"] == "done" and j["kind"] == "run" and j["progress"]["done"] == 1
    assert any(x["id"] == jid for x in client.get("/jobs?kind=run").json())


def test_jobs_and_runs_survive_a_restart_and_running_jobs_are_marked_interrupted(tmp_path):
    from strandbeest_api.jobs import JobStore

    app = create_app(tmp_path)
    c = TestClient(app)
    jid = c.post("/runs", json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.4, "settle": 0.2}}}).json()["job_id"]
    j = wait(c, jid)
    assert j["status"] == "done"
    rid = j["result"]["id"]
    app.state.workers.stop()
    # simulate a crash: one job left 'running' in the database
    store = JobStore(tmp_path / "strandbeest.db")
    stuck = store.create("run", {"design": DESIGN})
    store.claim_next()
    app2 = create_app(tmp_path)
    c2 = TestClient(app2)
    try:
        assert c2.get(f"/jobs/{jid}").json()["status"] == "done"
        assert c2.get(f"/jobs/{stuck}").json()["status"] == "failed"
        assert "interrupted" in c2.get(f"/jobs/{stuck}").json()["error"]
        assert c2.get("/runs").json()[0]["id"] == rid
    finally:
        app2.state.workers.stop()


def test_queued_jobs_can_be_cancelled(tmp_path):
    app = create_app(tmp_path, workers=0)  # nothing consumes the queue, so the job stays queued
    c = TestClient(app)
    jid = c.post("/runs", json={"design": DESIGN}).json()["job_id"]
    assert c.get(f"/jobs/{jid}").json()["status"] == "queued"
    assert c.post(f"/jobs/{jid}/cancel").json()["cancel_requested"] is True
    assert c.get(f"/jobs/{jid}").json()["status"] == "cancelled"
    assert c.post(f"/jobs/{jid}/cancel").json()["cancel_requested"] is False  # already finished


def test_sweep_expands_a_grid_runs_each_point_and_reports_progress(client):
    body = {"design": DESIGN, "axes": [{"path": "scenario.solver.contact_stiffness", "values": [3000, 10000]},
                                       {"path": "design.walker.legs", "values": [4, 6]}],
            "overrides": {"run": {"revolutions": 0.5, "settle": 0.2}}}
    r = client.post("/sweeps", json=body).json()
    assert r["points"] == 4
    j = wait(client, r["job_id"], tries=800)
    assert j["status"] == "done", j
    rows = j["result"]["rows"]
    assert len(rows) == 4 and j["progress"]["done"] == 4
    assert {(row["point"]["scenario.solver.contact_stiffness"], row["point"]["design.walker.legs"]) for row in rows} == {(3000, 4), (3000, 6), (10000, 4), (10000, 6)}
    assert all(row["run_id"] for row in rows)
    assert len(client.get("/runs?limit=10").json()) >= 4  # each point is a real, stored run


def test_sweep_rejects_bad_axes_and_oversized_grids(client):
    bad = client.post("/sweeps", json={"design": DESIGN, "axes": [{"path": "walker.legs", "values": [4]}]})
    assert bad.status_code == 422
    big = client.post("/sweeps", json={"design": DESIGN, "axes": [{"path": "scenario.solver.iterations", "values": list(range(10, 100))}]})
    assert big.status_code == 422


def test_export_serves_stl_files_and_the_bar_list(client):
    e = client.post("/exports", json=DESIGN).json()
    parts = client.get(f"/exports/{e['export_id']}/parts").json()
    assert len(parts["bars"]) == 11 and parts["bars"][0]["part"] in parts["parts"]
    stl = client.get(f"/exports/{e['export_id']}/stl/frame_plate")
    assert stl.status_code == 200 and len(stl.content) > 200
    assert client.get(f"/exports/{e['export_id']}/stl/nope").status_code == 404


def test_sweep_axis_can_set_linked_paths():
    from strandbeest_api.sweeps import expand

    pts = expand([{"path": "scenario.walker.foot_friction", "also": ["scenario.terrain.friction"], "values": [0.5, 1.0]}])
    assert pts == [
        {"scenario.walker.foot_friction": 0.5, "scenario.terrain.friction": 0.5},
        {"scenario.walker.foot_friction": 1.0, "scenario.terrain.friction": 1.0},
    ]


def _raw_csv(seconds=10.0, rate=100, omega=2.0, cpr=12, gear=100):
    import math

    lines = ["# fw=test", "t_ms,enc,current_mA,load_raw,wind_pulses,pwm"]
    for i in range(int(seconds * rate)):
        tt = i / rate
        lines.append(f"{int(tt * 1000)},{round(omega * tt / (2 * math.pi) * gear * cpr)},{100 + 40 * math.sin(omega * tt):.1f},,,")
    return "\n".join(lines) + "\n"


def test_rig_convert_returns_a_valid_measurement_with_quality(client):
    cal = {"counts_per_motor_rev": 12, "gear_ratio": 100, "kt_nm_per_a": 0.5, "idle_current_ma": 100, "calibrated": True}
    r = client.post("/rig/convert", json={"raw_csv": _raw_csv(), "calibration": cal, "name": "r1", "design_id": DESIGN["id"], "design_name": "jansen-small-6leg", "omega": 2.0, "raw_name": "r1.csv"})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["provenance"]["source"] == "rig" and doc["quality"]["warnings"] == []
    assert doc["schema_version"] == 2 and doc["name"] == "r1" and doc["design_id"] == DESIGN["id"] and len(doc["id"]) == 26
    assert doc["quality"]["speed_mean_rad_s"] == pytest.approx(2.0, rel=0.02)
    # the result can be saved and then compared like any other measurement
    assert client.post("/measurements", json=doc).status_code == 200


def test_rig_convert_reports_bad_input_as_422_and_serves_a_template(client):
    bad = client.post("/rig/convert", json={"raw_csv": "a,b\n1,2\n", "name": "x", "design_id": DESIGN["id"]})
    assert bad.status_code == 422 and "missing required columns" in bad.text
    assert client.post("/rig/convert", json={"name": "x"}).status_code == 422
    assert client.get("/rig/calibration-template").json()["calibrated"] is False


def test_replay_serves_frames_scene_and_a_nominal_stride(client):
    jid = client.post("/runs", json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.6, "settle": 0.2}}}).json()["job_id"]
    j = wait(client, jid)
    assert j["status"] == "done" and j["result"]["frames_file"] == "frames.npz"
    r = client.get(f"/runs/{j['result']['id']}/replay").json()
    n, b = len(r["t"]), len(r["scene"]["bodies"])
    assert n > 5 and len(r["pos"]) == n and len(r["pos"][0]) == b and len(r["quat"][0][0]) == 4
    assert len(r["contact"][0]) == 6 and r["scene"]["geoms"] and r["info"]["drive"] == "motor"
    assert r["nominal_stride_m"] == pytest.approx(0.27, rel=0.1)  # 6 legs, 2 mm units: about 133 units per revolution


def test_replay_of_an_unrecorded_run_is_a_clear_404(client):
    jid = client.post("/runs", json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.4, "settle": 0.2, "frame_rate": 0}}}).json()["job_id"]
    j = wait(client, jid)
    assert client.get(f"/runs/{j['result']['id']}/replay").status_code == 404


# ---- E2-02: documents written before ids existed stay usable --------------------------------------------------------
from strandbeest_common.ids import is_ulid, legacy_ulid  # noqa: E402

V1_DIR = schema_dir().parent / "contracts" / "migration" / "v1"


def test_a_v1_measurement_is_accepted_stored_with_an_id_and_found_by_its_old_name(client):
    v1 = json.loads((V1_DIR / "measurement-example.json").read_text())
    saved = client.post("/measurements", json=v1).json()
    assert saved["id"] == legacy_ulid("measurement", "example-motor-no-wind") and saved["name"] == "example-motor-no-wind"
    by_id = client.get(f"/measurements/{saved['id']}").json()
    by_old_name = client.get("/measurements/example-motor-no-wind").json()
    assert by_id == by_old_name and by_id["schema_version"] == 2
    assert client.get("/measurements").json()[0]["design_id"] == legacy_ulid("design", v1["design_name"])


def test_a_v1_design_posted_to_the_api_is_stored_as_v2_with_a_stable_id(client):
    v1 = json.loads((V1_DIR / "design-jansen-small-6leg.json").read_text())
    assert client.post("/designs/validate", json=v1).json()["ok"] is True
    saved = client.post("/designs", json=v1).json()
    assert saved["id"] == legacy_ulid("design", "jansen-small-6leg")
    assert client.get("/designs/jansen-small-6leg").json()["id"] == saved["id"]


def test_new_runs_get_ulids_and_point_at_their_design_by_id(client):
    jid = client.post("/runs", json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.4, "settle": 0.2}}}).json()["job_id"]
    doc = wait(client, jid)["result"]
    assert is_ulid(doc["id"]) and doc["design_id"] == DESIGN["id"] and doc["schema_version"] == 2
    listed = client.get("/runs").json()[0]
    assert listed["id"] == doc["id"] and listed["design_id"] == DESIGN["id"]


def test_a_v1_run_folder_is_indexed_and_served_by_its_old_and_new_id(tmp_path):
    old = "25844b8f5918"
    run = json.loads((V1_DIR / "run-example.json").read_text())
    run["id"] = old
    (tmp_path / "runs" / old).mkdir(parents=True)
    (tmp_path / "runs" / old / "run.json").write_text(json.dumps(run))
    app = create_app(tmp_path, workers=0)
    try:
        c = TestClient(app)
        new = legacy_ulid("run", old)
        assert c.get("/runs").json()[0]["id"] == new
        assert c.get(f"/runs/{old}").json()["id"] == new
        assert c.get(f"/runs/{new}").json()["aliases"] == [old]
    finally:
        app.state.workers.stop()
