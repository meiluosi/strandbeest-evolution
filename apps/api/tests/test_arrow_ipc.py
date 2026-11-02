"""End-to-end tests for Apache Arrow IPC streaming telemetry endpoint (M6-01)."""

import json
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
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
        time.sleep(0.2)
    return j


def test_arrow_ipc_stream_from_real_simulation(client):
    jid = client.post(
        "/runs",
        json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.8, "settle": 0.2}}},
    ).json()["job_id"]
    j = wait(client, jid)
    assert j["status"] == "done", j
    doc = j["result"]
    rid = doc["id"]

    # 1. Fetch full telemetry arrow stream
    res = client.get(f"/runs/{rid}/telemetry.arrow")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.apache.arrow.stream"

    # 2. Open stream using pyarrow directly
    reader = pa.ipc.open_stream(res.content)
    table = reader.read_all()
    assert table.num_rows > 0

    col_names = set(table.column_names)
    assert {"t", "pos", "quat", "contact", "foot_pos", "foot_force", "com"}.issubset(col_names)
    assert {"psi", "x", "torque"}.issubset(col_names)

    # 3. Verify schema metadata
    meta_bytes = table.schema.metadata.get(b"meta")
    assert meta_bytes is not None
    meta = json.loads(meta_bytes.decode("utf-8"))
    assert "metrics" in meta
    assert "diagnosis" in meta
    assert "events" in meta
    assert meta["info"]["legs"] == DESIGN["walker"]["legs"]
    assert meta["revolutions"] is not None and meta["revolutions"] > 0
    assert "shapes" in meta
    assert meta["shapes"]["pos"][0] == table.num_rows

    # 4. Verify shapes metadata
    assert b"_strandbeest_shapes" in table.schema.metadata
    shapes = json.loads(table.schema.metadata[b"_strandbeest_shapes"].decode("utf-8"))
    assert "pos" in shapes and shapes["pos"][0] == table.num_rows


def test_arrow_ipc_layer_filtering(client):
    jid = client.post(
        "/runs",
        json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.6, "settle": 0.2}}},
    ).json()["job_id"]
    j = wait(client, jid)
    assert j["status"] == "done", j
    rid = j["result"]["id"]

    # Layer: feet,events
    res_feet = client.get(f"/runs/{rid}/telemetry.arrow?layers=feet,events")
    assert res_feet.status_code == 200
    reader_feet = pa.ipc.open_stream(res_feet.content)
    table_feet = reader_feet.read_all()
    col_feet = set(table_feet.column_names)

    assert "t" in col_feet
    assert "foot_pos" in col_feet
    assert "foot_force" in col_feet
    assert "pos" not in col_feet
    assert "quat" not in col_feet
    assert "contact" not in col_feet
    assert "psi" not in col_feet

    meta_feet = json.loads(table_feet.schema.metadata[b"meta"].decode("utf-8"))
    assert "events" in meta_feet
    assert "energy" not in meta_feet

    # Layer: poses
    res_poses = client.get(f"/runs/{rid}/telemetry.arrow?layers=poses")
    assert res_poses.status_code == 200
    table_poses = pa.ipc.open_stream(res_poses.content).read_all()
    col_poses = set(table_poses.column_names)

    assert {"t", "pos", "quat", "contact"}.issubset(col_poses)
    assert "foot_force" not in col_poses
    assert "foot_pos" not in col_poses
    assert "torque" not in col_poses


def test_arrow_ipc_max_frames_downsampling(client):
    jid = client.post(
        "/runs",
        json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.8, "settle": 0.2}}},
    ).json()["job_id"]
    j = wait(client, jid)
    assert j["status"] == "done", j
    rid = j["result"]["id"]

    res = client.get(f"/runs/{rid}/telemetry.arrow?max_frames=10")
    assert res.status_code == 200
    table = pa.ipc.open_stream(res.content).read_all()
    assert 1 <= table.num_rows <= 15


def test_arrow_ipc_404_for_unknown_or_unrecorded(client):
    assert client.get("/runs/nonexistent/telemetry.arrow").status_code == 404

    # Run without recorded frames (frame_rate: 0)
    jid = client.post(
        "/runs",
        json={"design": DESIGN, "ensemble": False, "overrides": {"run": {"revolutions": 0.3, "settle": 0.1, "frame_rate": 0}}},
    ).json()["job_id"]
    j = wait(client, jid)
    assert j["status"] == "done"
    assert client.get(f"/runs/{j['result']['id']}/telemetry.arrow").status_code == 404


def test_arrow_ipc_npz_fallback_without_parquet(client, tmp_path):
    """Verify fallback when only frames.npz exists (legacy run archives)."""
    # Create fake run directory with only npz files
    rid = "01TESTLEGACYNPZRUN000000000"
    rdir = tmp_path / "runs" / rid
    rdir.mkdir(parents=True, exist_ok=True)

    n_frames = 50
    t = np.linspace(0.0, 2.0, n_frames)
    pos = np.zeros((n_frames, 10, 3), dtype=np.float32)
    quat = np.zeros((n_frames, 10, 4), dtype=np.float32)
    contact = np.ones((n_frames, 6), dtype=bool)

    np.savez(rdir / "frames.npz", t=t, pos=pos, quat=quat, contact=contact)
    np.savez(rdir / "arrays.npz", t=t, psi=t * 2, x=t * 0.5, torque=np.sin(t))
    (rdir / "run.json").write_text(json.dumps({
        "id": rid,
        "design_id": DESIGN["id"],
        "metrics": {"stride": 0.15},
        "scenario": {"walker": {"legs": 6, "unit": 0.001}},
    }))

    res = client.get(f"/runs/{rid}/telemetry.arrow")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.apache.arrow.stream"

    table = pa.ipc.open_stream(res.content).read_all()
    assert table.num_rows > 0
    assert "pos" in table.column_names
    assert "psi" in table.column_names
