"""Tests for automated run explainer and invariant-audited diagnostic reporter (A-05)."""

import json
from pathlib import Path
import pytest
from strandbeest_agent import default_registry, Session, Workspace
from strandbeest_agent.explainer import build_explanation_context, explain_run


def test_explain_normal_completed_run():
    run_doc = {
        "id": "run_01_normal",
        "design_id": "des_jansen_1",
        "design_name": "Jansen Normal",
        "stalled": False,
        "metrics": {
            "stride_per_rev": 0.42,
            "mean_torque": 5.2,
            "peak_torque": 12.0,
            "max_loop_violation": 0.0012,
            "max_penetration": 0.003,
            "energy_in_per_rev": 32.5,
        },
        "evidence": {
            "level": "E2",
            "downgraded": False,
            "downgrade_reasons": [],
        },
        "diagnosis": [],
        "events": [
            {"t": 0.15, "kind": "foot_touchdown", "leg": 1},
            {"t": 0.45, "kind": "foot_liftoff", "leg": 1},
        ],
    }

    ctx = build_explanation_context(run_doc)
    assert not ctx["stalled"]
    assert not ctx["invariants"]["loop_broken"]
    assert not ctx["invariants"]["excessive_penetration"]
    assert len(ctx["timeline"]) == 2

    res = explain_run(run_doc)
    assert "Simulation completed normally" in res["summary"]
    assert res["evidence_level"] == "E2"
    assert not res["downgraded"]
    assert "Max Loop Violation: 0.0012 m (OK)" in res["report_markdown"]
    assert "[0.150s] foot_touchdown leg=1" in res["report_markdown"]


def test_explain_stalled_run_with_diagnostics():
    run_doc = {
        "id": "run_02_stalled",
        "stalled": True,
        "metrics": {
            "stride_per_rev": 0.08,
            "mean_torque": 18.5,
            "peak_torque": 20.0,
            "max_loop_violation": 0.002,
            "max_penetration": 0.004,
        },
        "evidence": {
            "level": "E1",
            "downgraded": False,
        },
        "diagnosis": [
            {
                "code": "motor_torque_saturation",
                "severity": "error",
                "message": "Motor reached maximum output torque of 20 N·m without overcoming terrain resistance.",
                "evidence": {"peak_torque": 20.0, "limit": 20.0},
            }
        ],
        "events": [
            {"t": 1.25, "kind": "motor_saturation", "detail": {"current_torque": 20.0}},
            {"t": 1.30, "kind": "crank_stalled", "detail": {"velocity": 0.001}},
        ],
    }

    res = explain_run(run_doc)
    assert "Simulation stalled (diagnosis: motor_torque_saturation)" in res["summary"]
    assert "Root Cause Analysis" in res["report_markdown"]
    assert "[ERROR] motor_torque_saturation" in res["report_markdown"]
    assert "[1.250s] motor_saturation" in res["report_markdown"]


def test_explain_loop_broken_structural_failure():
    run_doc = {
        "id": "run_03_broken",
        "stalled": False,
        "metrics": {
            "stride_per_rev": 0.1,
            "max_loop_violation": 0.015,  # > 0.005 m limit
            "max_penetration": 0.002,
        },
        "evidence": {
            "level": "E0",
            "downgraded": True,
            "downgrade_reasons": ["kinematic_loop_rupture"],
        },
        "diagnosis": [],
    }

    res = explain_run(run_doc)
    assert "Simulation completed with kinematic loop rupture" in res["summary"]
    assert "Max Loop Violation: 0.0150 m (VIOLATED)" in res["report_markdown"]
    assert res["downgraded"]
    assert "kinematic_loop_rupture" in res["report_markdown"]


def test_explain_actively_downgrades_on_unmarked_rupture():
    """Even if run_doc did not set downgraded=True, explainer must actively synthesize downgrade on invariant breach."""
    run_doc = {
        "id": "run_unmarked_failure",
        "stalled": False,
        "metrics": {
            "max_loop_violation": 0.008,  # > 0.005 m limit
            "max_penetration": 0.025,  # > 0.02 m limit
        },
        "evidence": {
            "level": "E2",
            "downgraded": False,  # Untruthfully marked as not downgraded by upstream
            "downgrade_reasons": [],
        },
    }

    res = explain_run(run_doc)
    assert res["downgraded"] is True
    assert "kinematic loop violated" in res["report_markdown"]
    assert "excessive terrain penetration" in res["report_markdown"]



def test_simulate_explain_tool_in_registry(tmp_path):
    ws = Workspace(tmp_path / "ws")
    reg = default_registry()
    assert "simulate.explain" in reg.names()

    # Create dummy run in workspace
    run_dir = ws.root / "runs" / "test_run_01"
    run_dir.mkdir(parents=True)
    dummy_run = {
        "id": "test_run_01",
        "design_id": "d1",
        "stalled": False,
        "metrics": {
            "max_loop_violation": 0.0005,
            "max_penetration": 0.001,
            "stride_per_rev": 0.35,
        },
        "evidence": {"level": "E2", "downgraded": False},
        "events": [],
        "diagnosis": [],
        "provenance": {"engine": "mujoco"},
    }
    (run_dir / "run.json").write_text(json.dumps(dummy_run))

    session = Session()
    res = reg.call(ws, session, "simulate.explain", {"run": "test_run_01"})
    assert "summary" in res
    assert "report_markdown" in res
    assert res["evidence_level"] == "E2"


def test_explain_centered_failure_window():
    """Centered failure-window timeline extracts events around t_fault with launch and final summaries."""
    # 25 events spaced across 10 seconds; critical stall happens at t = 5.0
    events = [{"t": 0.0, "kind": "crank_start"}]
    for i in range(1, 10):
        events.append({"t": float(i * 0.4), "kind": "foot_step", "leg": i % 4})
    # Fault event at t = 5.0
    events.append({"t": 4.7, "kind": "foot_touchdown", "leg": 2})
    events.append({"t": 5.0, "kind": "crank_stalled", "detail": {"velocity": 0.0}})
    events.append({"t": 5.2, "kind": "motor_saturation", "detail": {"torque": 20.0}})
    for i in range(11, 20):
        events.append({"t": float(5.0 + i * 0.3), "kind": "holding_stalled"})

    run_doc = {
        "id": "run_long_failure",
        "stalled": True,
        "metrics": {"max_loop_violation": 0.001, "max_penetration": 0.002},
        "evidence": {"level": "E1", "downgraded": False},
        "diagnosis": [],
        "events": events,
    }

    res = explain_run(run_doc)
    report = res["report_markdown"]

    # Initial launch must be summarized
    assert "[Launch] [0.000s] crank_start" in report
    # Events around t = 5.0 in [4.5s, 5.5s] must be included
    assert "[4.700s] foot_touchdown leg=2" in report
    assert "[5.000s] crank_stalled" in report
    assert "[5.200s] motor_saturation" in report
    # Intermediate non-fault events outside window should be omitted
    assert "... (9 events omitted prior to fault window) ..." in report
    # Final state summary
    assert "[Final]" in report


def test_explain_detects_toggle_position_jam():
    """Deep diagnosis identifies toggle position singularity and severe mechanical advantage drop."""
    run_doc = {
        "id": "run_toggle_jam",
        "stalled": True,
        "metrics": {
            "min_mechanical_advantage": 0.008,  # < 0.05 threshold
            "singularity_proximity": 0.98,
            "max_loop_violation": 0.001,
            "max_penetration": 0.001,
        },
        "evidence": {"level": "E1", "downgraded": False},
        "diagnosis": [],
        "events": [
            {"t": 0.1, "kind": "crank_start"},
            {"t": 1.45, "kind": "toggle_jam", "detail": {"angle_rad": 3.1415}},
        ],
    }

    res = explain_run(run_doc)
    assert "TOGGLE_POSITION_JAM" in res["summary"]
    assert "TOGGLE_POSITION_JAM" in res["report_markdown"]
    assert "toggle position singularity" in res["report_markdown"]


def test_explain_detects_gait_desync_tipping():
    """Deep diagnosis identifies gait desynchronization causing vehicle tipping and instability."""
    run_doc = {
        "id": "run_desync_tipping",
        "stalled": False,
        "metrics": {
            "max_tilt_rad": 0.52,  # > 0.35 rad threshold (~30 degrees)
            "support_polygon_margin": -0.08,
            "max_loop_violation": 0.001,
            "max_penetration": 0.002,
        },
        "evidence": {"level": "E1", "downgraded": False},
        "diagnosis": [],
        "events": [
            {"t": 0.1, "kind": "crank_start"},
            {"t": 2.2, "kind": "tipping", "detail": {"pitch_rad": 0.52}},
        ],
    }

    res = explain_run(run_doc)
    assert "GAIT_DESYNC_TIPPING" in res["report_markdown"]
    assert "support polygon" in res["report_markdown"]

