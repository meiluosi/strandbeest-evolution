"""H2-01 unit tests for K2 double-support static friction wedge and observation-v3 cohort resolution."""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "hardening_k2_wedge_and_cohort",
    ROOT / "packages" / "sim" / "scripts" / "hardening_k2_wedge_and_cohort.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_case61_coarse_and_finer_stalls_occur_at_identical_six_fold_symmetric_wedge():
    k2_study = json.loads((ROOT / "experiments" / "hardening-k2-contact-study-2026-11-04.json").read_text())
    k2_rows = {r["case"]: r for r in k2_study["studies"]["coupled_cohort"]["record"]["rows"]}
    sc61 = k2_rows[61]["scenario"]

    psi_finer = 0.5511524312156284
    psi_coarse = 7.881535262757964
    leg_period = 2.0 * math.pi / 6.0
    assert (psi_coarse - psi_finer) / leg_period == pytest.approx(7.0, abs=1e-7)

    w_finer = MODULE.analyze_two_foot_wedge(sc61, psi_finer, 2, 3)
    w_coarse = MODULE.analyze_two_foot_wedge(sc61, psi_coarse, 3, 4)

    for w in (w_finer, w_coarse):
        assert w["foot_height_diff_m"] < 2e-6
        assert w["jn_psi_m_per_rad"][0] > 0.0 and w["jn_psi_m_per_rad"][1] < 0.0
        assert w["jt_psi_m_per_rad"][0] < 0.0 and w["jt_psi_m_per_rad"][1] > 0.0
        assert w["horizontal_jacobian_jump_mm_per_rev"] == pytest.approx(619.8049, rel=1e-4)
        assert w["static_wedge_torque_capacity_nm"] == pytest.approx(0.349583, rel=1e-4)
        assert w["wedge_exceeds_motor_limit"] is True
        assert w["lcp_rigid_converged"] is True
        assert abs(w["lcp_rigid_v_psi_rad_s"]) < 1e-12
        assert abs(w["lcp_rigid_v_x_m_s"]) < 1e-12
        assert w["lcp_rigid_motor_torque_nm"] == pytest.approx(0.3, rel=1e-9)


def test_case20_coarse_stall_is_a_two_foot_static_friction_wedge():
    k2_study = json.loads((ROOT / "experiments" / "hardening-k2-contact-study-2026-11-04.json").read_text())
    k2_rows = {r["case"]: r for r in k2_study["studies"]["coupled_cohort"]["record"]["rows"]}
    sc20 = k2_rows[20]["scenario"]

    w20 = MODULE.analyze_two_foot_wedge(sc20, 5.205442862998071, 1, 2)
    assert w20["foot_height_diff_m"] < 1e-6
    assert w20["static_wedge_torque_capacity_nm"] == pytest.approx(0.333393, rel=1e-4)
    assert w20["wedge_exceeds_motor_limit"] is True
    assert w20["lcp_rigid_converged"] is True
    assert abs(w20["lcp_rigid_v_psi_rad_s"]) < 1e-12
    assert w20["lcp_rigid_motor_torque_nm"] == pytest.approx(0.3, rel=1e-9)


def test_recorded_k2_observation_study_resolves_case16_without_faking_pass():
    doc = json.loads((ROOT / "experiments" / "hardening-k2-wedge-and-observation-2026-11-04.json").read_text())
    c16 = doc["case16_all_step_observation_resolution"]
    assert c16["integration_steps"] == 71972
    assert c16["airborne_steps"] == 2228
    assert c16["all_step_airborne_share"] < 0.05
    assert c16["sampled_record_every_20_airborne_share"] > 0.05
    assert c16["observation_issues"] == []
    assert c16["v2_status_without_observation"] == "failed"
    assert c16["v2_status_with_observation"] == "unverified"
    assert c16["legacy_v1_findings_preserved"] == ["support"]

    cohort = doc["k2_64_case_cohort_with_observation_v3"]
    assert cohort["v2_counts"] == {"passed": 0, "failed": 0, "unverified": 64}
    assert cohort["mujoco_contact_v3_v2_counts"] == {"passed": 0, "failed": 0, "unverified": 64}
