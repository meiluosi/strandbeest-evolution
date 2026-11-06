from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from strandbeest_calib.bayes import DigitalTwinModel
from strandbeest_calib.video_twin_pipeline import (
    VideoDigitalTwinPipelineResult,
    run_video_digital_twin_pipeline,
)
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir, validate
from strandbeest_rig.video_track import (
    CameraIntrinsics,
    MultiKeypointTrackResult,
    track_keypoints,
)
from strandbeest_sim import run, scenario_from_design


def make_aruco_img(marker_id: int, size_px: int = 50, dict_name: str = "DICT_4X4_50") -> np.ndarray:
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    marker = cv2.aruco.generateImageMarker(d, marker_id, size_px)
    return cv2.copyMakeBorder(marker, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)


def make_test_model():
    doc = json.loads((schema_dir() / "examples/design-jansen-small-6leg.json").read_text())
    doc["walker"]["legs"] = 2
    design = Design(doc)
    scenario = scenario_from_design(
        design,
        {
            "run": {"settle": 0.05, "max_time": 0.25, "revolutions": 1.5},
            "drive": {"omega": 4.0, "ramp": 0.03, "max_torque": 0.3},
        },
    )
    return DigitalTwinModel(design, scenario)


def generate_synthetic_tracking_from_native(model: DigitalTwinModel, true_pin_friction: float = 0.0015):
    """Generate a high-fidelity synthetic track result from native forward MuJoCo simulation."""
    times = np.linspace(0.0, 0.15, 16)
    pred = model.predict({"pin_friction": true_pin_friction}, times)

    fps = 100.0  # 10 ms per frame
    n_frames = len(times)
    w, h = 1000, 700

    hip_img = make_aruco_img(7, 40)
    crank_img = make_aruco_img(12, 40)
    foot_img = make_aruco_img(23, 40)

    # Scale: 1 pixel = 1 mm -> 0.001 m/px
    mpp = 0.001
    marker_mm = 40.0

    frames = []
    for i in range(n_frames):
        frame = np.full((h, w), 255, dtype=np.uint8)

        # Center hip around (250, 200)
        hip_px_x = int(250 + pred.x_hip[i] / mpp)
        hip_px_y = 200

        # Crank marker rotated around separate pivot offset in x by 220 px to avoid visual overlap
        crank_r_m = 0.04
        crank_px_x = int(hip_px_x + 220 + (crank_r_m * math.cos(pred.crank_angle[i])) / mpp)
        crank_px_y = int(hip_px_y - (crank_r_m * math.sin(pred.crank_angle[i])) / mpp)

        # Foot marker relative to hip (foot in Jansen linkage is ~167 mm below hip)
        foot_px_x = int(hip_px_x + pred.foot_path[i, 0] / mpp)
        foot_px_y = int(hip_px_y - pred.foot_path[i, 1] / mpp)

        for img, cx, cy in [(hip_img, hip_px_x, hip_px_y), (crank_img, crank_px_x, crank_px_y), (foot_img, foot_px_x, foot_px_y)]:
            sh, sw = img.shape[:2]
            y0, y1 = cy - sh // 2, cy - sh // 2 + sh
            x0, x1 = cx - sw // 2, cx - sw // 2 + sw
            frame[y0:y1, x0:x1] = img

        frames.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))

    intr = CameraIntrinsics(
        camera_matrix=np.array([[800.0, 0.0, 500.0], [0.0, 800.0, 350.0], [0.0, 0.0, 1.0]], dtype=float),
        dist_coeffs=np.zeros(5, dtype=float),
        image_size=(w, h),
        reprojection_error=0.05,
    )

    track_res = track_keypoints(
        frames,
        marker_ids={"hip": 7, "crank": 12, "foot": 23},
        marker_mm=marker_mm,
        fps=fps,
        intrinsics=intr,
        subpixel=True,
        synthetic=True,
    )
    return track_res, times, pred


def test_video_digital_twin_pipeline_end_to_end():
    model = make_test_model()
    true_friction = 0.0018
    priors = {"pin_friction": (0.0004, 0.004)}

    track_res, times, native_pred = generate_synthetic_tracking_from_native(model, true_friction)
    assert track_res.synthetic is True
    assert track_res.detected_fractions["hip"] > 0.90
    assert track_res.detected_fractions["foot"] > 0.90
    assert track_res.detected_fractions["crank"] > 0.90

    # Run complete end-to-end video inversion pipeline
    result = run_video_digital_twin_pipeline(
        model,
        track_res,
        priors,
        n_samples=250,
        burn_in=80,
        seed=42,
        emulator_points=8,
        validation_points=3,
        profile_grid=7,
        training_fraction=0.7,
    )

    assert isinstance(result, VideoDigitalTwinPipelineResult)
    assert result.synthetic is True
    assert result.emulator_valid is True

    # Parameter MAP estimate should recover the ballpark physical friction
    est_friction = result.parameter_estimates["pin_friction"]
    assert priors["pin_friction"][0] <= est_friction <= priors["pin_friction"][1]

    # Check forward simulation closure
    assert result.calibrated_trajectory_rms >= 0.0
    assert "foot_x" in result.forward_channel_nrmse
    assert "foot_y" in result.forward_channel_nrmse
    assert "omega" in result.forward_channel_nrmse

    # Check that CalibrationProfile was generated and valid
    profile_dict = result.calibration_report.profile.to_dict()
    assert profile_dict["parameters"]["pin_friction"] == pytest.approx(est_friction)
    assert "pin_friction" in result.identifiable_parameters

    # Check that serialization roundtrips cleanly
    res_dict = result.to_dict()
    assert res_dict["measurement_id"] == result.measurement_id
    assert res_dict["design_id"] == model.design.id
    assert res_dict["emulator_valid"] is True


def test_video_digital_twin_pipeline_rejects_missing_synthetic_declaration():
    model = make_test_model()
    track_res, _, _ = generate_synthetic_tracking_from_native(model)
    track_res.synthetic = None

    with pytest.raises(ValueError, match="synthetic"):
        run_video_digital_twin_pipeline(model, track_res, {"pin_friction": (0.0005, 0.003)})


def test_video_digital_twin_pipeline_rejects_physical_without_rig_provenance():
    model = make_test_model()
    track_res, _, _ = generate_synthetic_tracking_from_native(model)
    track_res.synthetic = False

    with pytest.raises(ValueError, match="rig_provenance is required"):
        run_video_digital_twin_pipeline(model, track_res, {"pin_friction": (0.0005, 0.003)})
