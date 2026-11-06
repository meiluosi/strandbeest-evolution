"""Predeclared end-to-end digital twin video tracking to forward simulation validation (H3-03).

Runs complete pipeline:
  1. Synthetic video frame generation with camera intrinsics
  2. Multi-keypoint ArUco sub-pixel tracking (hip, crank, foot)
  3. Materialization to schema-valid Measurement asset
  4. Native MuJoCo Bayesian calibration with RBF surrogate and independent holdout checks
  5. Execution writeback to CalibrationProfile
  6. Closed-loop forward MuJoCo validation
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

from strandbeest_calib.bayes import DigitalTwinModel
from strandbeest_calib.video_twin_pipeline import run_video_digital_twin_pipeline
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_rig.video_track import (
    CameraIntrinsics,
    track_keypoints,
)
from strandbeest_sim import scenario_from_design

ROOT = Path(__file__).resolve().parents[3]
OUT_PATH = ROOT / "experiments" / "digital-twin-video-inversion-2026-11-06.json"


def make_aruco_img(marker_id: int, size_px: int = 40, dict_name: str = "DICT_4X4_50") -> np.ndarray:
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    marker = cv2.aruco.generateImageMarker(d, marker_id, size_px)
    return cv2.copyMakeBorder(marker, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)


def main():
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
    model = DigitalTwinModel(design, scenario)

    true_pin_friction = 0.0016
    times = np.linspace(0.0, 0.15, 16)
    pred = model.predict({"pin_friction": true_pin_friction}, times)

    fps = 100.0
    n_frames = len(times)
    w, h = 1000, 700

    hip_img = make_aruco_img(7, 40)
    crank_img = make_aruco_img(12, 40)
    foot_img = make_aruco_img(23, 40)

    mpp = 0.001
    marker_mm = 40.0

    frames = []
    for i in range(n_frames):
        frame = np.full((h, w), 255, dtype=np.uint8)

        hip_px_x = int(250 + pred.x_hip[i] / mpp)
        hip_px_y = 200

        crank_r_m = 0.04
        crank_px_x = int(hip_px_x + 220 + (crank_r_m * math.cos(pred.crank_angle[i])) / mpp)
        crank_px_y = int(hip_px_y - (crank_r_m * math.sin(pred.crank_angle[i])) / mpp)

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

    priors = {"pin_friction": (0.0004, 0.004)}
    pipeline_result = run_video_digital_twin_pipeline(
        model,
        track_res,
        priors,
        n_samples=500,
        burn_in=150,
        seed=123,
        emulator_points=10,
        validation_points=3,
        profile_grid=9,
        training_fraction=0.7,
    )

    res_dict = pipeline_result.to_dict()
    res_dict["task"] = "H3-03"
    res_dict["date"] = "2026-11-06"
    res_dict["ground_truth_pin_friction"] = true_pin_friction
    res_dict["camera"] = {
        "camera_matrix": intr.camera_matrix.tolist(),
        "image_size": list(intr.image_size),
        "reprojection_error_px": intr.reprojection_error,
    }
    res_dict["tracking_metrics"] = {
        "fps": track_res.fps,
        "frames": track_res.frames,
        "detected_fractions": track_res.detected_fractions,
        "metres_per_pixel": track_res.metres_per_pixel,
    }

    OUT_PATH.write_text(json.dumps(res_dict, indent=2, allow_nan=False) + "\n")
    print(f"H3-03 Video Digital Twin Inversion successful!")
    print(f"Measurement ID: {res_dict['measurement_id']}")
    print(f"Ground truth pin friction: {true_pin_friction}")
    print(f"Recovered MAP pin friction: {pipeline_result.parameter_estimates['pin_friction']:.6f}")
    print(f"Identifiable parameters: {pipeline_result.identifiable_parameters}")
    print(f"Emulator valid (holdout normalized RMSE <= 3.0): {pipeline_result.emulator_valid}")
    print(f"Calibrated trajectory foot RMS: {pipeline_result.calibrated_trajectory_rms * 1000:.3f} mm")
    print(f"Total pipeline time: {pipeline_result.total_pipeline_time_s:.2f} s")


if __name__ == "__main__":
    main()
