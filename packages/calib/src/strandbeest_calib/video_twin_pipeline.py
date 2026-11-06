"""End-to-end digital twin video tracking to forward MuJoCo simulation pipeline (H3-03).

Coordinates:
  1. Multi-keypoint tracking results (hip, crank, foot) and camera calibration
  2. Materialization into a schema-valid Measurement asset with explicit alignment,
     units, and 1-sigma uncertainties
  3. Bayesian parameter inference (calibrate_physical_twin) with native MuJoCo forward runs,
     RBF surrogate, leave-one-out error bounds, independent parameter-space holdout checks,
     and profile likelihood identifiability analysis
  4. Execution-level writeback into a CalibrationProfile
  5. Native MuJoCo forward simulation closure and holdout trajectory comparison
"""
from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from strandbeest_common.ids import new_ulid
from strandbeest_common.schemas import validate
from strandbeest_rig.video_track import MultiKeypointTrackResult

from .bayes import CalibrationProfile, CalibrationReport, DigitalTwinModel
from .physical_inference import calibrate_physical_twin


EMULATOR_VALIDATION_SIGMA_LIMIT: float = 3.0


def _safe_channel_nrmse(pred: np.ndarray, obs: np.ndarray) -> float:
    """Compute normalized root-mean-square error with safeguard against zero or non-finite denominator."""
    denom = float(np.mean(obs**2))
    if denom <= 1e-12 or not math.isfinite(denom):
        return 0.0
    return float(np.sqrt(np.mean((pred - obs) ** 2) / denom))


@dataclass
class VideoDigitalTwinPipelineResult:
    """End-to-end outcome of video tracking to forward physical simulation."""

    measurement_id: str
    design_id: str
    synthetic: bool
    calibration_report: CalibrationReport
    nominal_trajectory_rms: float
    calibrated_trajectory_rms: float
    rms_reduction_ratio: float
    forward_channel_nrmse: dict[str, float]
    parameter_estimates: dict[str, float]
    identifiable_parameters: dict[str, bool]
    emulator_valid: bool
    total_pipeline_time_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurement_id": self.measurement_id,
            "design_id": self.design_id,
            "synthetic": self.synthetic,
            "nominal_trajectory_rms_m": self.nominal_trajectory_rms,
            "calibrated_trajectory_rms_m": self.calibrated_trajectory_rms,
            "rms_reduction_ratio": self.rms_reduction_ratio,
            "forward_channel_nrmse": self.forward_channel_nrmse,
            "parameter_estimates": self.parameter_estimates,
            "identifiable_parameters": self.identifiable_parameters,
            "emulator_valid": self.emulator_valid,
            "total_pipeline_time_s": self.total_pipeline_time_s,
            "calibration_profile": self.calibration_report.profile.to_dict(),
            "validation_summary": {
                "native_calls": self.calibration_report.validation.get("native_calls"),
                "native_seconds": self.calibration_report.validation.get("native_seconds"),
                "emulator_holdout_normalized_rmse": self.calibration_report.validation.get("emulator_holdout_normalized_rmse"),
                "native_time_holdout_normalized_rmse": self.calibration_report.validation.get("native_time_holdout_normalized_rmse"),
            },
        }


def run_video_digital_twin_pipeline(
    model: DigitalTwinModel,
    track_result: MultiKeypointTrackResult,
    priors: dict[str, tuple[float, float]],
    *,
    uncertainties: dict[str, float] | None = None,
    name: str = "video-digital-twin-inversion",
    crank_direction: int = 1,
    n_samples: int = 600,
    burn_in: int = 200,
    seed: int = 42,
    emulator_points: int = 12,
    validation_points: int = 3,
    profile_grid: int = 9,
    training_fraction: float = 0.7,
    rig_provenance: dict[str, Any] | None = None,
) -> VideoDigitalTwinPipelineResult:
    """Execute end-to-end video tracking -> Measurement -> Bayesian inversion -> forward MuJoCo validation.

    Args:
        model: Configured forward DigitalTwinModel (MuJoCo backend).
        track_result: MultiKeypointTrackResult from video_track.track_keypoints.
        priors: Prior bounds for calibratable parameters (e.g. {'pin_friction': (1e-4, 1e-2)}).
        uncertainties: Channel 1-sigma uncertainties in SI units (m, rad, rad/s).
        name: Name for generated CalibrationProfile.
        crank_direction: Direction multiplier (+1 or -1) mapping video rotation to model rotation.
        n_samples: MCMC posterior sample budget.
        burn_in: MCMC burn-in sample budget.
        seed: Deterministic PRNG seed.
        emulator_points: Number of Latin Hypercube points for RBF emulator training.
        validation_points: Independent parameter-space points for emulator validation.
        profile_grid: Number of grid evaluations for profile likelihood.
        training_fraction: Time-domain fraction used for training vs holdout validation.
        rig_provenance: Optional instrument calibration dict when track_result is physical (synthetic=False).
    """
    t_start = time.perf_counter()

    if track_result.synthetic is None:
        raise ValueError("track_result must declare synthetic=True or False")

    default_unc = {
        "t": 0.001,
        "psi": 0.02,
        "omega": 0.05,
        "foot_x": 0.002,
        "foot_y": 0.002,
        "x": 0.002,
    }
    unc = {**default_unc, **(uncertainties or {})}

    from .conditions import scenario_conditions

    # Construct provenance with alignment matching model requirements
    measurement_id = new_ulid()
    if track_result.synthetic:
        provenance = {
            "source": "simulator",
            "notes": "Synthetic digital twin video tracking inversion.",
            "calibration": {
                "units": {"t": "s", "psi": "rad", "omega": "rad/s", "foot_x": "m", "foot_y": "m", "x": "m"},
                "uncertainty_kind": "absolute_1sigma",
                "uncertainty": unc,
                "alignment": {
                    "time_origin": "drive_start",
                    "foot_index": model.foot_index,
                    "coordinates": "world_xz_hip_relative",
                },
                "generator": {
                    "model": "PhysicsBackend video tracking observation adapter",
                    "forward_model": copy.deepcopy(model.provenance),
                },
            },
        }
    else:
        if not rig_provenance:
            raise ValueError("rig_provenance is required for physical video tracking")
        provenance = copy.deepcopy(rig_provenance)
        cal = provenance.setdefault("calibration", {})
        cal["units"] = {"t": "s", "psi": "rad", "omega": "rad/s", "foot_x": "m", "foot_y": "m", "x": "m"}
        cal["uncertainty_kind"] = "absolute_1sigma"
        cal["uncertainty"] = unc
        cal["alignment"] = {
            "time_origin": "drive_start",
            "foot_index": model.foot_index,
            "coordinates": "world_xz_hip_relative",
        }

    # 1. Video tracking to schema-valid Measurement asset
    measurement_doc = track_result.to_measurement(
        measurement_id=measurement_id,
        design_id=model.design.id,
        name=f"tracked-video-{name}",
        conditions=scenario_conditions(model.scenario),
        provenance=provenance,
        crank_direction=crank_direction,
        alignment=provenance["calibration"]["alignment"],
    )
    validate("measurement", measurement_doc)

    # 2. Bayesian calibration with native MuJoCo runs + RBF surrogate + independent holdout
    report = calibrate_physical_twin(
        model,
        measurement_doc,
        priors,
        n_samples=n_samples,
        burn_in=burn_in,
        seed=seed,
        name=name,
        emulator_points=emulator_points,
        validation_points=validation_points,
        profile_grid=profile_grid,
        training_fraction=training_fraction,
    )

    # 3. Native MuJoCo forward simulation closure
    # Compare nominal prediction (prior midpoint) vs calibrated MAP prediction against measured trajectories
    times = np.asarray(measurement_doc["channels"]["t"], dtype=float)
    lo = np.log([priors[k][0] for k in priors])
    hi = np.log([priors[k][1] for k in priors])
    nominal_params = {k: float(math.exp(0.5 * (lo[i] + hi[i]))) for i, k in enumerate(priors)}

    nominal_pred = model.predict(nominal_params, times)
    calibrated_pred = model.predict(report.map_estimate, times)

    # Compute trajectory RMS errors (foot_x, foot_y, hip_x) in metres
    obs_foot_x = np.asarray(measurement_doc["channels"]["foot_x"], dtype=float)
    obs_foot_y = np.asarray(measurement_doc["channels"]["foot_y"], dtype=float)
    obs_omega = np.asarray(measurement_doc["channels"]["omega"], dtype=float)
    obs_x = np.asarray(measurement_doc["channels"]["x"], dtype=float)

    obs_foot = np.column_stack([obs_foot_x, obs_foot_y])
    nom_residual_foot = nominal_pred.foot_path - obs_foot
    cal_residual_foot = calibrated_pred.foot_path - obs_foot

    nom_foot_rms = float(np.sqrt(np.mean(np.sum(nom_residual_foot**2, axis=1))))
    cal_foot_rms = float(np.sqrt(np.mean(np.sum(cal_residual_foot**2, axis=1))))

    # Channel NRMSEs with safe non-zero denominator checking
    channel_nrmse = {
        "foot_x": _safe_channel_nrmse(calibrated_pred.foot_path[:, 0], obs_foot_x),
        "foot_y": _safe_channel_nrmse(calibrated_pred.foot_path[:, 1], obs_foot_y),
        "omega": _safe_channel_nrmse(calibrated_pred.omega, obs_omega),
        "x": _safe_channel_nrmse(calibrated_pred.x_hip, obs_x),
    }

    rms_reduction = (nom_foot_rms - cal_foot_rms) / nom_foot_rms if nom_foot_rms > 0 else 0.0

    identifiable = {
        k: bool(report.profile.uncertainty[k]["identifiable"])
        for k in priors
        if k in report.profile.uncertainty
    }

    emu_norm_rmse = float(report.validation.get("emulator_holdout_normalized_rmse", float("inf")))
    emulator_valid = emu_norm_rmse <= EMULATOR_VALIDATION_SIGMA_LIMIT

    t_end = time.perf_counter()

    return VideoDigitalTwinPipelineResult(
        measurement_id=measurement_id,
        design_id=model.design.id,
        synthetic=bool(track_result.synthetic),
        calibration_report=report,
        nominal_trajectory_rms=nom_foot_rms,
        calibrated_trajectory_rms=cal_foot_rms,
        rms_reduction_ratio=rms_reduction,
        forward_channel_nrmse=channel_nrmse,
        parameter_estimates=report.map_estimate,
        identifiable_parameters=identifiable,
        emulator_valid=emulator_valid,
        total_pipeline_time_s=t_end - t_start,
    )
