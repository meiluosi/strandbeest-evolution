from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from strandbeest_calib.transducer_baseline import (
    ATI_GAMMA_15_50_FSR_AXIAL_N,
    ATI_GAMMA_15_50_FSR_TANGENTIAL_N,
    ATI_GAMMA_15_50_FSR_TORQUE_NM,
    ATI_GAMMA_15_50_SPEC,
    ATI_MAX_ZERO_DRIFT_TANGENTIAL_N,
    ATI_RATED_ZERO_DRIFT_FRACTION,
    TransducerSpecification,
    diagnose_transducer_drift,
)

ROOT = Path(__file__).resolve().parents[3]
DIAGNOSIS_PATH = ROOT / "experiments" / "external-crank-medium-error-diagnosis-2026-11-04.json"


def test_ati_gamma_15_50_spec_constants():
    spec = ATI_GAMMA_15_50_SPEC
    assert spec.full_scale_tangential_n == pytest.approx(66.723324, rel=1e-5)
    assert spec.full_scale_axial_n == pytest.approx(200.16997, rel=1e-5)
    assert spec.full_scale_torque_nm == pytest.approx(5.64924, rel=1e-4)
    assert spec.rated_zero_drift_fraction == 0.005
    assert spec.rated_zero_drift_tangential_n == pytest.approx(0.333617, rel=1e-5)


@pytest.mark.parametrize(
    "offset,expected",
    [
        (0.0, True),
        (0.0308, True),
        (-0.1383, True),
        (0.3336, True),
        (0.3337, False),
        (-0.35, False),
        (float("nan"), False),
        (float("inf"), False),
        (float("-inf"), False),
    ],
)
def test_transducer_spec_validates_offsets(offset: float, expected: bool):
    assert ATI_GAMMA_15_50_SPEC.validate_offset(offset) == expected


def test_diagnose_transducer_drift_analytical_behavior():
    dt = 0.005
    inertia = 0.003716
    radius = 0.10287
    b = 0.002626
    tau_c = 0.0148
    bias = -0.0019

    # Generate synthetic steady rotation with an injected transducer force offset of +0.05 N
    w_steady = 3.0
    true_tau_diss = b * w_steady + tau_c + bias  # N*m
    injected_force_offset_n = 0.05
    injected_torque_offset_nm = injected_force_offset_n * radius

    # Sensor reads applied torque with the offset
    measured_torque = np.full(200, true_tau_diss + injected_torque_offset_nm)
    omega = np.full(201, w_steady)

    diag = diagnose_transducer_drift(
        trial_name="synthetic_trial",
        condition="synthetic_condition",
        split="holdout",
        torque=measured_torque,
        omega=omega,
        dt=dt,
        inertia=inertia,
        radius=radius,
        viscous_damping=b,
        coulomb_friction=tau_c,
        torque_bias=bias,
    )

    assert diag.implied_force_offset_n == pytest.approx(injected_force_offset_n, rel=1e-4)
    assert diag.within_rated_spec is True
    assert diag.implied_force_offset_pct_fsr == pytest.approx(
        (injected_force_offset_n / ATI_GAMMA_15_50_FSR_TANGENTIAL_N) * 100.0, rel=1e-4
    )
    # Sensitivity formula: Delta_tau / b = Delta_Ft * r / b
    assert diag.steady_velocity_sensitivity_rad_s == pytest.approx(
        (injected_force_offset_n * radius) / b, rel=1e-4
    )


def test_holdout_trials_all_satisfy_ati_manufacturer_zero_drift_spec():
    assert DIAGNOSIS_PATH.exists()
    diag_doc = json.loads(DIAGNOSIS_PATH.read_text())
    sensitivity = diag_doc["sensor_zero_drift_sensitivity"]
    assert sensitivity["all_holdout_offsets_within_spec"] is True

    # Median offset should be ~0.0308 N (0.046% FSR) and max ~0.1383 N (0.207% FSR)
    assert sensitivity["holdout_median_abs_force_offset_n"] == pytest.approx(0.03077, abs=1e-4)
    assert sensitivity["holdout_max_abs_force_offset_n"] == pytest.approx(0.13833, abs=1e-4)
    assert sensitivity["holdout_median_abs_force_offset_pct_full_scale"] < 0.1
    assert sensitivity["holdout_max_abs_force_offset_pct_full_scale"] < 0.5

    # Check that each individual holdout record has within_rated_spec == True
    holdouts = [t for t in diag_doc["trials"] if t["split"] == "holdout"]
    assert len(holdouts) == 16
    for h in holdouts:
        assert h["within_rated_spec"] is True
        assert abs(h["implied_force_zero_offset_n"]) <= ATI_MAX_ZERO_DRIFT_TANGENTIAL_N


def test_zero_drift_compensation_significantly_reduces_velocity_nrmse():
    diag_doc = json.loads(DIAGNOSIS_PATH.read_text())
    coulomb_models = diag_doc["models"]

    raw_holdout = coulomb_models["coulomb_3param"]["holdout"]
    comp_holdout = coulomb_models["coulomb_3param_zero_drift_compensated"]["holdout"]

    # Pooled velocity RMSE should drop from ~2.17 rad/s down to ~1.06 rad/s (> 50% error reduction)
    assert raw_holdout["pooled_velocity_rmse_rad_s"] == pytest.approx(2.1704, abs=1e-3)
    assert comp_holdout["pooled_velocity_rmse_rad_s"] == pytest.approx(1.0612, abs=1e-3)
    assert comp_holdout["pooled_velocity_rmse_rad_s"] < 0.55 * raw_holdout["pooled_velocity_rmse_rad_s"]

    # Fast speed error stays low (< 10%)
    assert comp_holdout["condition_velocity_nrmse"]["ccw_fast"] < 0.08
    assert comp_holdout["condition_velocity_nrmse"]["cw_fast"] < 0.10

    # Medium speed error reduces from 117% and 51% down to ~45% and ~36%
    assert comp_holdout["condition_velocity_nrmse"]["ccw_medium"] < raw_holdout["condition_velocity_nrmse"]["ccw_medium"]
    assert comp_holdout["condition_velocity_nrmse"]["cw_medium"] < raw_holdout["condition_velocity_nrmse"]["cw_medium"]
