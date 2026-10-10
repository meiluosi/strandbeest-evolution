"""A-04: the design benchmark scores on blind scenes, refuses to be gamed, and its baselines run through the same tools."""
import json
from pathlib import Path

import pytest
from strandbeest_agent import Workspace, default_registry
from strandbeest_agent.bench import BASELINES, BENCH, Score, ToolClient, load_tasks, run_agent, score
from strandbeest_agent.registry import Session
from strandbeest_agent.workspace import ToolError
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir

TASKS = {t["id"]: t for t in load_tasks()["tasks"]}
START = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json").doc
BLIND = json.loads((BENCH / "blind-scenes.json").read_text())["scenes"]


def edited(**params):
    d = json.loads(json.dumps(START))
    d["linkage"]["params"].update(params)
    return d


def test_the_blind_scenes_are_not_revealed_by_any_tool_or_prompt(tmp_path):
    reg = default_registry()
    text = json.dumps(reg.describe()) + json.dumps({t["id"]: (t["intent"], t["visible_scenes"]) for t in TASKS.values()})
    for name in BLIND:
        assert name not in text
    assert "bumps" not in json.dumps({t["id"]: t["intent"] for t in TASKS.values()})
    ws = Workspace(tmp_path)
    client = ToolClient(ws, TASKS["stride-on-flat"])
    did = client.call("design.create", example="jansen-small-6leg")["design_id"]
    for scene in ("slope", "bumps", "slope-a"):  # not visible for this task (or not a scene at all)
        with pytest.raises(ToolError) as e:
            client.call("simulate.run", design=did, scene=scene)
        assert e.value.code == "scene_not_allowed"
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert "bumps-a" not in p.read_text(errors="ignore")


def test_invalid_designs_and_designs_outside_the_envelope_score_zero_without_simulating():
    task = TASKS["stride-on-flat"]
    broken = score(task, START, edited(m=START["linkage"]["params"]["m"] * 1.4), start_value=0.28)  # inside the envelope, but the crank no longer closes
    assert broken.score == 0 and broken.reason == "invalid_design" and "cannot_assemble" in broken.detail["problems"]
    huge = score(task, START, edited(m=START["linkage"]["params"]["m"] * 1.45), start_value=0.28)
    assert huge.score == 0 and huge.reason == "outside_envelope"
    legs = json.loads(json.dumps(START))
    legs["walker"]["legs"] = 8
    assert score(task, START, legs, start_value=0.28).reason == "outside_envelope"
    topo = json.loads(json.dumps(START))
    topo["linkage"]["joints"].append({"id": "X", "centers": ["C", "K"], "radii": [30.0, 25.0], "side": -1})
    assert score(task, START, topo, start_value=0.28).reason == "outside_envelope"


@pytest.mark.slow
def test_the_starting_design_scores_exactly_zero_and_a_distrusted_run_scores_zero(monkeypatch):
    task = TASKS["stride-on-flat"]
    s = score(task, START, START)
    assert s.reason == "ok" and s.score == pytest.approx(0.0, abs=1e-9) and s.value == pytest.approx(s.start_value)
    from strandbeest_agent import bench

    class F:
        check = "loop_closure"

    monkeypatch.setattr("strandbeest_sim.skeptic.audit", lambda *a, **k: [F()])
    gamed = bench.score(task, START, edited(b=START["linkage"]["params"]["b"] * 1.05), start_value=s.start_value)
    assert gamed.score == 0 and gamed.reason == "distrusted_run"


@pytest.mark.slow
def test_a_baseline_agent_runs_through_the_tools_within_the_budget_and_is_scored(tmp_path):
    task = dict(TASKS["stride-on-flat"], budget={"sim_runs": 2, "ops": 10})
    result, spent = run_agent(task, BASELINES["cmaes-proxy"], tmp_path / "ws", seed=1)
    assert isinstance(result, Score) and spent["runs"] <= 2 + 1 and spent["ops"] <= 10
    assert result.reason in {"ok", "distrusted_run", "outside_envelope", "invalid_design"}
    audit = (tmp_path / "ws" / "audit.jsonl").read_text().splitlines()
    assert all(json.loads(l)["actor"]["id"] == "bench-agent" for l in audit)
