"""H2-01 follow-up study:
1. Exact diagnosis of the K2 double-support static friction wedge on Case 61 (dt=0.5 ms, 0.025 ms)
   and Case 20 (dt=0.5 ms), plus why both MuJoCo and K2 agree around +4.14..+4.35 mm/rev while
   differing from the zero-double-support geometric reference (+3.146 mm/rev) on Case 61.
2. Re-evaluation of the 64-case K2 cohort with all-step AuditObservation (observation-v3),
   resolving Case 16's record_every=20 sampling-cadence false failure (all-step airborne share
   3.096% <= 5%) so both the 64-case MuJoCo cohort and 64-case K2 cohort reach
   0 passed / 0 failed / 64 unverified under v2 while preserving legacy v1 findings verbatim.
3. Dual-solver (MuJoCo vs K2) dynamical stride comparison across the 64-case cohort.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from strandbeest_sim.audit import audit_report, reference_for_scenario
from strandbeest_sim.audit_observation import AuditObservation, observation_issues
from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.backends.k2_contact import solve_contacts
from strandbeest_sim.config import SimConfig
from strandbeest_sim.runner import run

ROOT = Path(__file__).resolve().parents[3]
K2_STUDY_PATH = ROOT / "experiments" / "hardening-k2-contact-study-2026-11-04.json"
MUJOCO_COHORT_PATH = ROOT / "experiments" / "hardening-g1-contact-v3-default-2026-11-04.json"
RIGID_CONV_PATH = ROOT / "experiments" / "hardening-g1-rigid-convergence-2026-11-04.json"
OUT_PATH = ROOT / "experiments" / "hardening-k2-wedge-and-observation-2026-11-04.json"
K2_TMP = Path("/tmp/beest-k2-contact-2026-11-04")


def analyze_two_foot_wedge(sc_dict: dict, psi_stall: float, leg_a: int, leg_b: int) -> dict:
    """Compute the exact K2 contact Jacobians and static friction wedge capacity at psi_stall."""
    sc = SimConfig.model_validate(sc_dict)
    be = K2Backend()
    from strandbeest_sim.registry import terrains

    be.build(sc, terrains.get(sc.terrain.kind)(sc))
    be._q = np.array([0.0, 0.0, 0.0, psi_stall], dtype=float)
    center_a, jn_a, jt_a = be._foot_contact_kinematics(leg_a)
    center_b, jn_b, jt_b = be._foot_contact_kinematics(leg_b)

    z_rel_a = float(center_a[1])
    z_rel_b = float(center_b[1])
    r_foot = sc.walker.foot_radius
    z_torso = r_foot - min(z_rel_a, z_rel_b) - 1e-5
    be._q = np.array([0.0, z_torso, 0.0, psi_stall], dtype=float)
    be._v = np.zeros(4, dtype=float)

    weight_n = float(be._m_total * sc.environment.gravity)
    mu = float(be._foot_friction)
    horiz_jac_jump = abs(float(jt_b[3] - jt_a[3]))
    # With equal normal load W/2 on each foot and opposing tangential Jacobians:
    wedge_torque_nm = 0.5 * weight_n * mu * horiz_jac_jump
    max_torque_nm = float(sc.drive.max_torque or 0.0)

    # Verify with solve_contacts at equal penetration (1e-5 m) and max motor torque:
    dt = 2.5e-5
    beta = 0.15
    sample = be._mass_terms()
    inverse = be._inverse_mass(sample.matrix)
    gravity = sample.gravity(be._gravity)
    v_free = inverse @ (gravity * dt)
    pen = 1e-5
    sol_rigid = solve_contacts(
        free_velocity=v_free,
        inverse_mass=inverse,
        normals=[jn_a, jn_b],
        tangents=[jt_a, jt_b],
        targets=[beta * pen / dt, beta * pen / dt],
        normal_compliance=[0.0, 0.0],
        friction=mu,
        motor_enabled=True,
        motor_desired=10.0 * dt,
        motor_damping_dt=sc.drive.kv * dt,
        motor_limit=max_torque_nm * dt,
        iterations=250,
    )

    return {
        "psi_stall_rad": psi_stall,
        "psi_mod_leg_period_rad": float(psi_stall % (2.0 * math.pi / sc.walker.legs)),
        "leg_a": leg_a,
        "leg_b": leg_b,
        "foot_z_rel_m": [z_rel_a, z_rel_b],
        "foot_height_diff_m": abs(z_rel_a - z_rel_b),
        "jn_psi_m_per_rad": [float(jn_a[3]), float(jn_b[3])],
        "jt_psi_m_per_rad": [float(jt_a[3]), float(jt_b[3])],
        "horizontal_jacobian_jump_m_per_rad": horiz_jac_jump,
        "horizontal_jacobian_jump_mm_per_rev": horiz_jac_jump * 2.0 * math.pi * 1000.0,
        "weight_n": weight_n,
        "mu": mu,
        "static_wedge_torque_capacity_nm": wedge_torque_nm,
        "motor_max_torque_nm": max_torque_nm,
        "wedge_exceeds_motor_limit": wedge_torque_nm > max_torque_nm,
        "lcp_rigid_converged": bool(sol_rigid.converged),
        "lcp_rigid_v_psi_rad_s": float(sol_rigid.velocity[3]),
        "lcp_rigid_v_x_m_s": float(sol_rigid.velocity[0]),
        "lcp_rigid_fn_n": [float(x / dt) for x in sol_rigid.normal],
        "lcp_rigid_ft_n": [float(x / dt) for x in sol_rigid.tangent],
        "lcp_rigid_motor_torque_nm": float(sol_rigid.motor / dt),
    }


def main() -> None:
    k2_study = json.loads(K2_STUDY_PATH.read_text())
    mj_cohort = json.loads(MUJOCO_COHORT_PATH.read_text())
    k2_rows = {r["case"]: r for r in k2_study["studies"]["coupled_cohort"]["record"]["rows"]}
    mj_rows = {r["case"]: r for r in mj_cohort["rows"]}

    # 1. Verify the exact symmetry of Case 61 coarse (dt=0.5ms) and finer (dt=0.025ms) stalls:
    psi_finer = 0.5511524312156284
    psi_coarse = 7.881535262757964
    leg_period = 2.0 * math.pi / 6.0
    period_multiple = (psi_coarse - psi_finer) / leg_period

    wedge_case61_finer = analyze_two_foot_wedge(k2_rows[61]["scenario"], psi_finer, 2, 3)
    wedge_case61_coarse = analyze_two_foot_wedge(k2_rows[61]["scenario"], psi_coarse, 3, 4)
    wedge_case20_coarse = analyze_two_foot_wedge(k2_rows[20]["scenario"], 5.205442862998071, 1, 2)

    # 2. Re-run Case 16 with current runner (which populates AuditObservation on every step)
    sc16 = SimConfig.model_validate(k2_rows[16]["scenario"])
    res16 = run(sc16, backend="k2")
    series16 = {"t": res16.t, "psi": res16.psi, "x": res16.x, **res16.series}
    obs_issues_16 = observation_issues(sc16, res16.metrics, series16, res16.audit_observation, "k2")
    audit16_with_obs = audit_report(
        sc16,
        res16.metrics,
        series16,
        res16.stalled,
        backend_name="k2",
        observation=res16.audit_observation,
    )
    audit16_without_obs = audit_report(
        sc16,
        res16.metrics,
        series16,
        res16.stalled,
        backend_name="k2",
        observation=None,
    )

    # 3. Re-evaluate the 64-case K2 cohort with all-step observation coverage:
    # In §76, Case 16 was the only v2 failure (sampled support 5.585% > 5% at record_every=20).
    # With AuditObservation (observation-v3), Case 16's all-step airborne share is 3.095648% <= 5%.
    k2_cohort_v2_counts = {"passed": 0, "failed": 0, "unverified": 0}
    k2_cohort_legacy_counts = {"passed": 0, "failed": 0}
    dual_solver_comparisons = []

    for idx in sorted(k2_rows):
        c_k2 = k2_rows[idx]
        c_mj = mj_rows[idx]
        if idx == 16:
            rep = audit16_with_obs
            metrics = res16.metrics
        else:
            rep = c_k2["audit"]
            metrics = c_k2["metrics"]
        k2_cohort_v2_counts[rep["status"]] += 1
        k2_cohort_legacy_counts["passed" if rep["legacy"]["passed"] else "failed"] += 1

        s_k2 = float(metrics["stride_per_rev"])
        s_mj = float(c_mj["metrics"]["stride_per_rev"])
        s_ref = float(rep["stride_reference"]["signed_stride_m_per_rev"])
        dual_solver_comparisons.append(
            {
                "index": idx,
                "stride_k2_m": s_k2,
                "stride_mujoco_m": s_mj,
                "stride_ref_m": s_ref,
                "k2_vs_mujoco_abs_diff_m": abs(s_k2 - s_mj),
                "k2_vs_mujoco_rel_diff_vs_mj": abs(s_k2 - s_mj) / max(abs(s_mj), 1e-12),
                "k2_vs_ref_rel_err": abs(s_k2 / s_ref - 1.0),
                "mujoco_vs_ref_rel_err": abs(s_mj / s_ref - 1.0),
            }
        )

    rel_diffs = [d["k2_vs_mujoco_rel_diff_vs_mj"] for d in dual_solver_comparisons]
    abs_diffs_mm = [d["k2_vs_mujoco_abs_diff_m"] * 1000.0 for d in dual_solver_comparisons]

    # Case 61 cross-solver summary:
    case61_summary = {
        "geometric_reference_mm_per_rev": 3.1456112456503276,
        "total_abs_foot_travel_mm_per_rev": 195.8878099869312,
        "cancellation_condition": 62.27337163645166,
        "handoff_velocity_jump_mm_per_rev": wedge_case61_finer["horizontal_jacobian_jump_mm_per_rev"],
        "mujoco_contact_v3_k2e6_dt1e4_mm_per_rev": float(mj_rows[61]["metrics"]["stride_per_rev"]) * 1000.0,
        "mujoco_stiff_k4e7_dt3p125e6_mm_per_rev": 4.350865752679717,
        "k2_coupled_dt1e4_mm_per_rev": 4.144446060246458,
        "k2_coupled_dt5e5_mm_per_rev": 4.151292241487395,
        "k2_vs_mujoco_stiff_diff_mm_per_rev": abs(4.151292241487395 - 4.350865752679717),
        "k2_vs_mujoco_stiff_rel_diff": abs(4.151292241487395 - 4.350865752679717) / 4.350865752679717,
        "psi_finer_stall_rad": psi_finer,
        "psi_coarse_stall_rad": psi_coarse,
        "leg_symmetry_period_rad": leg_period,
        "coarse_minus_finer_in_leg_periods": period_multiple,
    }

    output = {
        "date": "2026-11-04",
        "task": "H2-01",
        "case61_cross_solver_and_symmetry": case61_summary,
        "static_friction_wedge_diagnostics": {
            "case61_finer_dt25us": wedge_case61_finer,
            "case61_coarse_dt500us": wedge_case61_coarse,
            "case20_coarse_dt500us": wedge_case20_coarse,
        },
        "case16_all_step_observation_resolution": {
            "integration_steps": res16.audit_observation["integration_steps"],
            "observed_steps": res16.audit_observation["observed_steps"],
            "airborne_steps": res16.audit_observation["airborne_steps"],
            "all_step_airborne_share": res16.audit_observation["airborne_steps"] / res16.audit_observation["observed_steps"],
            "sampled_record_every_20_airborne_share": 21 / 376,
            "support_limit": 0.05,
            "observation_issues": obs_issues_16,
            "v2_status_without_observation": audit16_without_obs["status"],
            "v2_status_with_observation": audit16_with_obs["status"],
            "v2_findings_with_observation": [f["check"] for f in audit16_with_obs["findings"]],
            "legacy_v1_findings_preserved": [f["check"] for f in audit16_with_obs["legacy"]["findings"]],
        },
        "k2_64_case_cohort_with_observation_v3": {
            "v2_counts": k2_cohort_v2_counts,
            "legacy_v1_counts": k2_cohort_legacy_counts,
            "mujoco_contact_v3_v2_counts": {"passed": 0, "failed": 0, "unverified": 64},
        },
        "dual_solver_cohort_comparison": {
            "count": len(dual_solver_comparisons),
            "median_abs_diff_mm": float(np.median(abs_diffs_mm)),
            "p90_abs_diff_mm": float(np.percentile(abs_diffs_mm, 90)),
            "max_abs_diff_mm": float(np.max(abs_diffs_mm)),
            "median_rel_diff": float(np.median(rel_diffs)),
            "cases_within_5pct_between_solvers": int(sum(1 for r in rel_diffs if r <= 0.05)),
            "cases_within_10pct_between_solvers": int(sum(1 for r in rel_diffs if r <= 0.10)),
            "cases_within_15pct_between_solvers": int(sum(1 for r in rel_diffs if r <= 0.15)),
            "per_case": dual_solver_comparisons,
        },
    }
    OUT_PATH.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "dual_solver_cohort_comparison"}, indent=2))
    print("Dual solver summary:", {k: v for k, v in output["dual_solver_cohort_comparison"].items() if k != "per_case"})


if __name__ == "__main__":
    main()
