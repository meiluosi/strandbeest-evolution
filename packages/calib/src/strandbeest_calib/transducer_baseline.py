"""ATI Gamma 15/50 force transducer baseline model and zero-drift bounds (H4-01).

Manufacturer specification:
  Transducer: ATI Industrial Automation Gamma 15/50 6-DOF F/T Sensor
  Location: Apex, NC, USA
  Full scale range (FSR):
    Fx, Fy = 15.0 lbf = 66.723324 N
    Fz     = 45.0 lbf = 200.169973 N
    Tx, Ty, Tz = 50.0 lbf*in = 5.64924 N*m
  Rated zero-drift allowance under unrestrained ambient operating conditions:
    +/- 0.5% FSR (tangential force bound: +/- 0.333617 N).

Physical mechanism of velocity drift:
  For a scalar rotor with viscous damping b and moment of inertia I, a static tangential
  force offset Delta_Ft produces steady-state velocity shift:
    Delta_omega_inf = (Delta_Ft * r) / b
  For crank radius r = 0.10287 m and b = 0.002626 N*m*s/rad, a force offset of just
  0.031 N (0.046% FSR) produces Delta_omega_inf = 1.21 rad/s.
  At medium speed (~2.8 rad/s), this causes ~43% relative drift over open-loop integration,
  whereas at fast speed (~10.7 rad/s), the same offset causes only ~11% relative drift.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

# 15 lbf in Newtons = 15.0 * 4.4482216152605 N
ATI_GAMMA_15_50_FSR_TANGENTIAL_N: float = 15.0 * 4.4482216152605  # 66.7233242289075 N
ATI_GAMMA_15_50_FSR_AXIAL_N: float = 45.0 * 4.4482216152605  # 200.1699726867225 N
ATI_GAMMA_15_50_FSR_TORQUE_NM: float = 50.0 * 0.1129848290276167  # 5.649241451380835 N*m

# Manufacturer rated maximum single-axis zero drift without active re-zeroing
ATI_RATED_ZERO_DRIFT_FRACTION: float = 0.005  # +/- 0.5% FSR
ATI_MAX_ZERO_DRIFT_TANGENTIAL_N: float = ATI_GAMMA_15_50_FSR_TANGENTIAL_N * ATI_RATED_ZERO_DRIFT_FRACTION  # 0.333617 N


@dataclass(frozen=True)
class TransducerSpecification:
    """Documented instrument specification with explicit manufacturer bounds."""

    model_name: str
    manufacturer: str
    full_scale_tangential_n: float
    full_scale_axial_n: float
    full_scale_torque_nm: float
    rated_zero_drift_fraction: float
    rated_zero_drift_tangential_n: float
    citation: str

    def validate_offset(self, offset_n: float) -> bool:
        """Check whether an observed force offset falls strictly within the manufacturer rating."""
        if not math.isfinite(offset_n):
            return False
        return abs(offset_n) <= self.rated_zero_drift_tangential_n


ATI_GAMMA_15_50_SPEC = TransducerSpecification(
    model_name="ATI Gamma 15/50 6-DOF F/T Transducer",
    manufacturer="ATI Industrial Automation, Apex, NC",
    full_scale_tangential_n=ATI_GAMMA_15_50_FSR_TANGENTIAL_N,
    full_scale_axial_n=ATI_GAMMA_15_50_FSR_AXIAL_N,
    full_scale_torque_nm=ATI_GAMMA_15_50_FSR_TORQUE_NM,
    rated_zero_drift_fraction=ATI_RATED_ZERO_DRIFT_FRACTION,
    rated_zero_drift_tangential_n=ATI_MAX_ZERO_DRIFT_TANGENTIAL_N,
    citation="ATI Industrial Automation, Gamma Multi-Axis Force/Torque Sensor System Manual",
)


@dataclass
class TransducerZeroDriftDiagnosis:
    """Per-trial diagnostic of implied transducer zero drift and steady velocity sensitivity."""

    trial_name: str
    condition: str
    split: str
    mean_observed_tangential_force_n: float
    mean_speed_rad_s: float
    implied_force_offset_n: float
    implied_force_offset_pct_fsr: float
    within_rated_spec: bool
    steady_velocity_sensitivity_rad_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_name": self.trial_name,
            "condition": self.condition,
            "split": self.split,
            "mean_observed_tangential_force_n": self.mean_observed_tangential_force_n,
            "mean_speed_rad_s": self.mean_speed_rad_s,
            "implied_force_offset_n": self.implied_force_offset_n,
            "implied_force_offset_pct_fsr": self.implied_force_offset_pct_fsr,
            "within_rated_spec": self.within_rated_spec,
            "steady_velocity_sensitivity_rad_s": self.steady_velocity_sensitivity_rad_s,
        }


def diagnose_transducer_drift(
    *,
    trial_name: str,
    condition: str,
    split: str,
    torque: Sequence[float] | np.ndarray,
    omega: Sequence[float] | np.ndarray,
    dt: float,
    inertia: float,
    radius: float,
    viscous_damping: float,
    coulomb_friction: float,
    torque_bias: float,
    spec: TransducerSpecification = ATI_GAMMA_15_50_SPEC,
) -> TransducerZeroDriftDiagnosis:
    """Compute the implied force transducer zero drift for a single trial and check against spec.

    Args:
        trial_name: Name of trial record.
        condition: Test condition (e.g. 'ccw_medium', 'cw_fast').
        split: 'train' or 'holdout'.
        torque: 1D array of applied torques (N*m).
        omega: 1D array of angular velocities (rad/s).
        dt: Time step (s).
        inertia: Crank rotor inertia (kg*m^2).
        radius: Crank radius (m).
        viscous_damping: Fitted viscous damping b (N*m*s/rad).
        coulomb_friction: Fitted dry Coulomb friction tau_c (N*m).
        torque_bias: Fitted torque bias (N*m).
        spec: TransducerSpecification instance.
    """
    if dt <= 0 or not math.isfinite(dt):
        raise ValueError("dt must be positive and finite")
    if radius <= 0 or not math.isfinite(radius):
        raise ValueError("radius must be positive and finite")
    if inertia <= 0 or not math.isfinite(inertia):
        raise ValueError("inertia must be positive and finite")

    omega_arr = np.asarray(omega, dtype=float)
    torque_arr = np.asarray(torque, dtype=float)

    if len(omega_arr) < 2 or not np.isfinite(omega_arr).all():
        raise ValueError("omega must contain at least 2 finite samples")
    if len(torque_arr) < 1 or not np.isfinite(torque_arr).all():
        raise ValueError("torque must contain at least 1 finite sample")

    duration_s = (len(omega_arr) - 1) * dt
    mean_w = float(np.mean(omega_arr))
    delta_w = float(omega_arr[-1] - omega_arr[0])

    # Observed mean dissipative torque from dynamic balance:
    # tau_app - I * domega/dt = tau_diss
    obs_diss_nm = float(np.mean(torque_arr) - inertia * delta_w / duration_s)

    # Predicted mean dissipative torque from fitted physical model:
    sign_w = math.copysign(1.0, mean_w) if abs(mean_w) > 1e-12 else 0.0
    pred_diss_nm = viscous_damping * mean_w + coulomb_friction * sign_w + torque_bias

    delta_tau_nm = obs_diss_nm - pred_diss_nm
    delta_ft_n = delta_tau_nm / radius
    pct_fsr = (abs(delta_ft_n) / spec.full_scale_tangential_n) * 100.0

    steady_vel_shift = abs(delta_tau_nm) / viscous_damping if viscous_damping > 0 else float("inf")

    return TransducerZeroDriftDiagnosis(
        trial_name=trial_name,
        condition=condition,
        split=split,
        mean_observed_tangential_force_n=float(np.mean(torque_arr) / radius),
        mean_speed_rad_s=mean_w,
        implied_force_offset_n=delta_ft_n,
        implied_force_offset_pct_fsr=pct_fsr,
        within_rated_spec=spec.validate_offset(delta_ft_n),
        steady_velocity_sensitivity_rad_s=steady_vel_shift,
    )
