"""E3-01: nothing downstream of the LinkageSpec is tied to Jansen's leg. A non-Jansen chain of dyads from the kinematics
corpus goes through design -> evaluate -> simulate -> export, and the front end derives its view from the same spec."""
import copy
import json
import time

import pytest
from fastapi.testclient import TestClient
from strandbeest_api import create_app
from strandbeest_common.ids import new_ulid
from strandbeest_common.schemas import schema_dir

ROOT = schema_dir().parent
BASE = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())
NON_JANSEN = ["fourbar-crank-rocker", "sixbar-extra-dyad"]


def design_with(name: str) -> dict:
    corpus = json.loads((ROOT / "contracts" / "kinematics" / f"{name}.json").read_text())
    d = copy.deepcopy(BASE)
    d.update(id=new_ulid(), name=f"test-{name}", linkage=corpus["spec"])
    return d


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, workers=1)
    yield TestClient(app)
    app.state.workers.stop()


def wait(client, jid, tries=240):
    for _ in range(tries):
        j = client.get(f"/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.5)
    return j


@pytest.mark.parametrize("name", NON_JANSEN)
def test_a_non_jansen_chain_is_designed_evaluated_exported_and_simulated(client, name):
    d = design_with(name)
    assert client.post("/designs/validate", json=d).json()["ok"] is True
    ev = client.post("/evaluate", json=d).json()
    assert ev["gait"]["width"] > 0

    ex = client.post("/exports", json=d).json()
    parts = client.get(f"/exports/{ex['export_id']}/parts").json()
    n_joints = len(d["linkage"]["joints"])
    # the export is derived from the joints: the crank plus one bar per circle centre of every joint, per leg set
    assert len(parts["bars"]) == 1 + 2 * n_joints
    assert ex["parts"] >= 1

    jid = client.post("/runs", json={"design": d, "ensemble": False, "overrides": {"run": {"revolutions": 0.6, "settle": 0.3}}}).json()["job_id"]
    j = wait(client, jid)
    assert j["status"] == "done", j
    assert j["result"]["design_id"] == d["id"] and j["result"]["scenario"]["walker"]["legs"] == d["walker"]["legs"]
    # the run completes and reports numbers; whether this chain walks well is a different question (it need not)
    assert j["result"]["metrics"]["stride_per_rev"] is not None
