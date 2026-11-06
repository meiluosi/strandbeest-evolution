"""Unit tests for V-03 / V1b Nansai et al. 2015 Literature Dynamics Replication."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from strandbeest_calib.nansai_literature import (
    CRANK_LENGTH_L2_M,
    JANSEN_CRANK_LENGTH_UNITS,
    JOINT_DAMPING_NMS_RAD,
    LINK_INERTIA_KG_M2,
    LINK_MASS_KG,
    NANSAI_2015_PRIMARY_DOI,
    NANSAI_2015_SECONDARY_DOI,
    NANSAI_REPORTED_HEIGHT_SHRINKAGE_PCT,
    NANSAI_REPORTED_PROTOTYPE_HEIGHT_CM,
    NANSAI_REPORTED_PROTOTYPE_WIDTH_CM,
    NANSAI_REPORTED_SIM_HEIGHT_CM,
    NANSAI_REPORTED_SIM_WIDTH_CM,
    NANSAI_REPORTED_WIDTH_SHRINKAGE_PCT,
    NANSAI_UNIT_M,
    QUADRUPED_LEGS,
    ROOT_DIR,
    build_nansai_scenario,
    extract_foot_trajectory_cycles,
    generate_nansai_validation_document,
    load_jansen_kinematic_reference,
    run_nansai_replication,
    run_nansai_simulation,
    save_nansai_validation_asset,
)


def test_nansai_constants_and_geometry_scale():
    """Verify literature constants match published values from Nansai 2015."""
    assert CRANK_LENGTH_L2_M == pytest.approx(0.05417, abs=1e-5)
    assert JANSEN_CRANK_LENGTH_UNITS == pytest.approx(15.0, abs=1e-5)
    assert NANSAI_UNIT_M == pytest.approx(0.05417 / 15.0, rel=1e-6)

    # Mechanical properties
    assert LINK_MASS_KG == pytest.approx(0.1, abs=1e-4)
    assert LINK_INERTIA_KG_M2 == pytest.approx(0.01, abs=1e-4)
    assert JOINT_DAMPING_NMS_RAD == pytest.approx(0.01, abs=1e-4)
    assert QUADRUPED_LEGS == 4

    # Published benchmark constants
    assert NANSAI_REPORTED_SIM_WIDTH_CM == pytest.approx(39.82, abs=0.01)
    assert NANSAI_REPORTED_SIM_HEIGHT_CM == pytest.approx(9.39, abs=0.01)
    assert NANSAI_REPORTED_PROTOTYPE_WIDTH_CM == pytest.approx(33.42, abs=0.01)
    assert NANSAI_REPORTED_PROTOTYPE_HEIGHT_CM == pytest.approx(7.59, abs=0.01)

    # Shrinkage rates
    assert NANSAI_REPORTED_WIDTH_SHRINKAGE_PCT == pytest.approx(16.07, abs=0.01)
    assert NANSAI_REPORTED_HEIGHT_SHRINKAGE_PCT == pytest.approx(19.17, abs=0.01)

    # DOI links
    assert "10.1155/2015/315673" in NANSAI_2015_PRIMARY_DOI
    assert "10.1177/1687814015573824" in NANSAI_2015_SECONDARY_DOI


def test_kinematic_reference_metrics():
    """Verify analytical kinematic gait metrics for Jansen linkage scaled to Nansai size."""
    kin = load_jansen_kinematic_reference(NANSAI_UNIT_M)
    assert kin["width_cm"] == pytest.approx(24.52, abs=0.05)
    assert kin["lift_cm"] == pytest.approx(8.11, abs=0.05)
    assert kin["stroke_length_cm"] == pytest.approx(20.61, abs=0.05)
    assert 0.40 <= kin["duty"] <= 0.46


def test_nansai_scenario_builder():
    """Verify scenario generation with matching parameters."""
    sc = build_nansai_scenario(omega=2.5, pitch_locked=True)
    # Check that it produces a valid Scenario instance
    assert sc.world.gravity == pytest.approx(9.81)

    # Check flattened config properties
    from strandbeest_sim.config import sim_config
    cfg = sim_config(sc)
    assert cfg.walker.legs == 4
    assert cfg.walker.unit == pytest.approx(NANSAI_UNIT_M)
    assert cfg.walker.joint_damping == pytest.approx(0.01)
    assert cfg.walker.pitch == "locked"
    assert cfg.drive.omega == pytest.approx(2.5)


def test_fast_simulation_and_trajectory_cycles():
    """Test rapid 3-revolution simulation (1 settle + 2 steady cycles) and cycle extraction."""
    sim_res = run_nansai_simulation(
        revolutions=3.0,
        settle_revs=1.0,
        omega=2.0,
        frame_rate=30,
        pitch_locked=True,
    )
    assert not sim_res.stalled
    assert sim_res.frames is not None
    assert "foot_pos" in sim_res.frames

    cycles, steady_pts = extract_foot_trajectory_cycles(
        sim_res, settle_revs=1.0, omega=2.0, target_cycles=2
    )
    assert len(cycles) == 2

    for c in cycles:
        # Stroke width should closely track the 24.52 cm kinematic loop width
        assert c.stroke_width_cm == pytest.approx(24.52, abs=0.2)
        # Lift height should match ~8.1 cm
        assert c.lift_height_cm == pytest.approx(8.1, abs=0.2)
        # Chassis stride per revolution should be positive and physical
        assert 0.35 <= c.stride_m <= 0.55
        # Stance flatness ripple should be finite and small
        assert 0.0 <= c.flatness_ripple_cm <= 3.0
        # Normal forces should be non-negative
        assert c.mean_normal_force_n > 0.0
        assert c.peak_normal_force_n >= c.mean_normal_force_n
        # Contact duty factor
        assert 0.3 <= c.contact_duty_factor <= 0.8

    # Cycle-to-cycle repeatability check (sub-millimeter precision)
    w_diff = abs(cycles[0].stroke_width_cm - cycles[1].stroke_width_cm)
    h_diff = abs(cycles[0].lift_height_cm - cycles[1].lift_height_cm)
    assert w_diff < 0.05
    assert h_diff < 0.05


def test_vertical_equilibrium_conservation():
    """Verify that ground normal forces integrate to balance gravitational weight."""
    result = run_nansai_replication(
        revolutions=3.0,
        settle_revs=1.0,
        omega=2.0,
        frame_rate=30,
        pitch_locked=True,
    )
    # The total vertical ground reaction force must balance static weight Mg within 3%
    assert result.vertical_equilibrium_ratio == pytest.approx(1.0, abs=0.03)
    assert result.expected_gravity_force_n == pytest.approx(result.total_walker_mass_kg * 9.81, rel=1e-3)
    assert result.mean_stroke_width_cm > 0.0
    assert result.mean_lift_height_cm > 0.0


def test_validation_document_schema_and_evidence():
    """Verify that generated validation document satisfies Evidence Level E1 criteria."""
    result = run_nansai_replication(
        revolutions=3.0,
        settle_revs=1.0,
        omega=2.0,
        frame_rate=30,
        pitch_locked=True,
    )
    doc = generate_nansai_validation_document(result)

    assert "E1" in doc["evidence_level"]
    assert "V-03" in doc["task"]
    assert "literature_references" in doc
    assert "primary" in doc["literature_references"]
    assert "secondary" in doc["literature_references"]

    refs = doc["literature_references"]
    assert "10.1155/2015/315673" in refs["primary"]["doi"]
    assert "10.1177/1687814015573824" in refs["secondary"]["doi"]

    # Verify comparison section
    comp = doc["literature_comparison"]
    assert "kinematic_analytical_baseline" in comp
    assert "dynamic_forward_simulation" in comp
    assert "nansai_published_data" in comp
    assert comp["nansai_published_data"]["prototype_width_shrinkage_pct"] == 16.07
    assert len(comp["reconciliation_findings"]) >= 5

    # Check JSON roundtrip
    serialized = json.dumps(doc)
    deserialized = json.loads(serialized)
    assert deserialized["task"] == doc["task"]
    assert deserialized["extracted_gait_metrics"]["stroke_width_cm"]["mean"] == doc["extracted_gait_metrics"]["stroke_width_cm"]["mean"]


def test_persisted_experiment_json_asset():
    """Verify the saved machine-readable asset in experiments/ directory."""
    asset_path = ROOT_DIR / "experiments" / "external-nansai-2015-literature-validation.json"
    assert asset_path.exists(), f"Expected validation asset at {asset_path}"

    data = json.loads(asset_path.read_text(encoding="utf-8"))
    assert "E1" in data["evidence_level"]
    assert "V-03" in data["task"]
    assert data["simulation_execution"]["steady_cycles_analyzed"] == 10
    assert len(data["cycle_details"]) == 10

    metrics = data["extracted_gait_metrics"]
    assert metrics["stroke_width_cm"]["mean"] == pytest.approx(24.52, abs=0.1)
    assert metrics["lift_height_cm"]["mean"] == pytest.approx(8.09, abs=0.1)
    assert metrics["ground_contact_forces"]["vertical_equilibrium_ratio"] == pytest.approx(1.0, abs=0.02)


def test_save_nansai_validation_asset_custom_path(tmp_path: Path):
    """Verify saving to custom destination."""
    custom_dest = tmp_path / "nansai_test_out.json"
    sample_doc = {
        "date": "2026-11-06",
        "task": "V-03",
        "evidence_level": "E1",
    }
    saved_path = save_nansai_validation_asset(sample_doc, custom_dest)
    assert saved_path == custom_dest
    assert custom_dest.exists()
    content = json.loads(custom_dest.read_text(encoding="utf-8"))
    assert content["task"] == "V-03"
