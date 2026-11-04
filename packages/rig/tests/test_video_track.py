from __future__ import annotations

import math
import cv2
import numpy as np
import pytest
from strandbeest_common.ids import new_ulid
from strandbeest_common.schemas import validate

from strandbeest_rig.video_track import (
    CameraIntrinsics,
    MultiKeypointTrackResult,
    calibrate_camera,
    track_keypoints,
)


def make_aruco_marker_img(marker_id: int, size_px: int = 60, dict_name: str = "DICT_4X4_50") -> np.ndarray:
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    marker = cv2.aruco.generateImageMarker(d, marker_id, size_px)
    return cv2.copyMakeBorder(marker, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)


def test_camera_intrinsics_undistort_points():
    K = np.array([[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    dist = np.array([0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    intr = CameraIntrinsics(camera_matrix=K, dist_coeffs=dist, image_size=(640, 480))
    pts = np.array([[320.0, 240.0], [100.0, 100.0], [500.0, 400.0]], dtype=np.float32)
    undist = intr.undistort_points(pts)
    assert np.allclose(pts, undist, atol=1e-3)


def test_calibrate_camera_synthetic_checkerboards():
    board_size = (7, 5)
    square_size_mm = 20.0
    w, h = 800, 600

    objp = np.zeros((board_size[1] * board_size[0], 3), np.float32)
    objp[:, :2] = np.mgrid[0 : board_size[0], 0 : board_size[1]].T.reshape(-1, 2) * (square_size_mm / 1000.0)

    # Generate synthetic checkerboard images by projecting 3D board corners with a known camera
    true_K = np.array([[600.0, 0.0, 400.0], [0.0, 600.0, 300.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    true_dist = np.zeros(5, dtype=np.float64)

    images = []
    for angle_deg in [-10, 0, 10]:
        rvec = np.array([0.0, np.radians(angle_deg), 0.0], dtype=np.float64)
        tvec = np.array([0.0, 0.0, 0.5], dtype=np.float64)
        proj_pts, _ = cv2.projectPoints(objp, rvec, tvec, true_K, true_dist)
        proj_pts = proj_pts.reshape(-1, 2)

        # Draw checkerboard image
        img = np.full((h, w), 255, dtype=np.uint8)
        # Draw black squares
        for r in range(board_size[1] + 1):
            for c in range(board_size[0] + 1):
                if (r + c) % 2 == 0:
                    x0 = int(250 + c * 35 + angle_deg * 2)
                    y0 = int(180 + r * 35)
                    img[y0 : y0 + 35, x0 : x0 + 35] = 0
        images.append(img)

    # Verify checkerboard corner detection and calibration
    intr = calibrate_camera(images, board_size=board_size, square_size_mm=square_size_mm)
    assert intr.camera_matrix.shape == (3, 3)
    assert intr.reprojection_error >= 0.0


def test_multi_keypoint_tracking_synthetic_video():
    marker_mm = 20.0
    marker_px = 60
    fps = 30.0
    duration = 1.0  # seconds
    n_frames = int(fps * duration)
    w, h = 1000, 500

    hip_marker = make_aruco_marker_img(7, marker_px)
    crank_marker = make_aruco_marker_img(12, marker_px)
    foot_marker = make_aruco_marker_img(23, marker_px)

    mpp = (marker_mm / 1000.0) / marker_px
    omega_true = 2.0 * math.pi * 1.5  # 1.5 rev/s = ~9.42 rad/s
    crank_radius_px = 50.0

    # Hip moves forward (0.05 m/s)
    hip_speed_px_s = 0.05 / mpp
    frames = []
    for i in range(n_frames):
        t = i / fps
        frame = np.full((h, w), 255, dtype=np.uint8)

        hip_x = int(150 + hip_speed_px_s * t)
        hip_y = 120

        # Crank pivot is offset from hip by 220 px
        pivot_x = hip_x + 220
        pivot_y = 120
        crank_theta = omega_true * t
        crank_x = int(pivot_x + crank_radius_px * math.cos(crank_theta))
        crank_y = int(pivot_y + crank_radius_px * math.sin(crank_theta))

        # Foot follows lower periodic path
        foot_x = int(hip_x + 100 + 40.0 * math.sin(crank_theta))
        foot_y = int(320 + 25.0 * math.cos(crank_theta))

        # Paste markers
        for img, cx, cy in [(hip_marker, hip_x, hip_y), (crank_marker, crank_x, crank_y), (foot_marker, foot_x, foot_y)]:
            sh, sw = img.shape[:2]
            frame[cy - sh // 2 : cy - sh // 2 + sh, cx - sw // 2 : cx - sw // 2 + sw] = img

        frames.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))

    result = track_keypoints(
        frames,
        marker_ids={"hip": 7, "crank": 12, "foot": 23},
        marker_mm=marker_mm,
        fps=fps,
        subpixel=True,
        synthetic=True,
    )

    assert isinstance(result, MultiKeypointTrackResult)
    assert result.synthetic is True
    assert result.tracking_metadata["frame_rate_source"] == "caller"
    assert result.frames == n_frames
    assert result.detected_fractions["hip"] > 0.95
    assert result.detected_fractions["crank"] > 0.95
    assert result.detected_fractions["foot"] > 0.95

    # Check angular velocity recovery
    # Due to unwrapping and spline differentiation, mean omega should match omega_true closely
    mean_omega = float(np.mean(np.abs(result.omega)))
    assert mean_omega == pytest.approx(omega_true, rel=0.10)

    # Check foot path relative to hip
    foot_rel = result.foot_path
    assert foot_rel.shape == (n_frames, 2)
    # y is positive upwards, so foot below hip should have negative y
    assert np.mean(foot_rel[:, 1]) < 0

    # Test closed foot curve sampling
    cx, cy = result.sample_foot_curve(num_points=50)
    assert len(cx) == 50
    assert len(cy) == 50
    assert not np.isnan(cx).any()
    assert not np.isnan(cy).any()


def test_missing_frames_are_subpixel_interpolated_with_warning():
    marker_mm = 20.0
    marker_px = 60
    fps = 30.0
    n_frames = 20
    w, h = 600, 400

    hip_marker = make_aruco_marker_img(7, marker_px)
    frames = []
    for i in range(n_frames):
        frame = np.full((h, w), 255, dtype=np.uint8)
        # Drop marker in frames 5, 6, 7 (15% dropped)
        if i not in (5, 6, 7):
            cx, cy = 200 + i * 5, 200
            sh, sw = hip_marker.shape[:2]
            frame[cy - sh // 2 : cy - sh // 2 + sh, cx - sw // 2 : cx - sw // 2 + sw] = hip_marker
        frames.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))

    res = track_keypoints(frames, marker_ids={"hip": 7}, marker_mm=marker_mm, fps=fps)
    assert res.detected_fractions["hip"] == pytest.approx(17 / 20)
    assert any("gaps interpolated" in w for w in res.warnings)
    # Check that trajectory has no NaNs because of subpixel interpolation
    assert not np.isnan(res.trajectories["hip"]).any()
    # Check trajectory monotonicity
    x_coords = res.trajectories["hip"][:, 0]
    assert np.all(np.diff(x_coords) > 0)


def track_metadata_fixture():
    """Only tests provenance plumbing, not physical measurement or E3 validation."""
    t = np.array([0.0, 0.1, 0.2])
    hip = np.column_stack([t * 0.1, np.zeros(3)])
    foot = np.tile([0.02, -0.08], (3, 1))
    return MultiKeypointTrackResult(
        t=t, trajectories={"hip": hip, "foot": hip + foot, "crank": hip + 0.01},
        omega=-np.ones(3), foot_path=foot, crank_angle=-t,
        fps=10.0, frames=3, detected_fractions={"hip": 1.0, "foot": 1.0, "crank": 1.0},
        metres_per_pixel=0.0003, synthetic=False, raw_source="test-fixture-only.mp4",
        camera_calibration={"camera_matrix": [[600, 0, 320], [0, 600, 240], [0, 0, 1]],
                            "dist_coeffs": [0, 0, 0, 0, 0], "image_size": [640, 480], "reprojection_error_px": 0.2},
        tracking_metadata={"marker_mm": 20.0, "frame_rate_source": "caller", "first_frame_index": 0},
    )


def measurement_kwargs():
    return {
        "measurement_id": new_ulid(), "design_id": new_ulid(), "name": "metadata-fixture-only",
        "conditions": {"kind": "motor_no_wind", "surface": "fixture"}, "crank_direction": -1,
        "provenance": {"source": "rig", "calibration": {
            "instrument": "fixture camera", "measured_on": "2026-11-01", "calibrated_on": "2026-10-31",
            "uncertainty": {"t": 0.001, "psi": 0.02, "omega": 0.05, "foot_x": 0.001, "foot_y": 0.001, "x": 0.001},
        }},
    }


def test_tracking_materializes_measurement_with_exact_identity_units_and_provenance():
    tracked = track_metadata_fixture()
    args = measurement_kwargs()
    doc = tracked.to_measurement(**args)
    validate("measurement", doc)
    assert doc["id"] == args["measurement_id"]
    assert doc["design_id"] == args["design_id"]
    assert doc["synthetic"] is False
    assert doc["provenance"]["raw_file"] == tracked.raw_source
    assert doc["provenance"]["calibration"]["camera"] == tracked.camera_calibration
    assert doc["provenance"]["calibration"]["units"]["foot_y"] == "m"
    assert doc["provenance"]["calibration"]["tracking"]["crank_direction"] == -1
    assert doc["provenance"]["calibration"]["uncertainty_kind"] == "absolute_1sigma"
    assert doc["channels"]["psi"] == [0, 0.1, 0.2]
    assert doc["channels"]["omega"] == [1, 1, 1]
    assert doc["channels"]["foot_y"] == [-0.08, -0.08, -0.08]
    assert "units" not in args["provenance"]["calibration"]  # caller metadata is not mutated


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda track, args: setattr(track, "synthetic", None), "declare synthetic"),
        (lambda track, args: setattr(track, "raw_source", None), "raw_file"),
        (lambda track, args: setattr(track, "camera_calibration", None), "camera"),
        (lambda track, args: args["provenance"]["calibration"].pop("measured_on"), "measured_on"),
        (lambda track, args: args["provenance"]["calibration"].pop("calibrated_on"), "calibrated_on"),
        (lambda track, args: args["provenance"]["calibration"]["uncertainty"].pop("foot_x"), "uncertainty"),
        (lambda track, args: args["provenance"]["calibration"].update(units={"foot_y": "mm"}), "units"),
        (lambda track, args: track.trajectories.pop("hip"), "tracked hip"),
        (lambda track, args: setattr(track, "t", np.zeros(3)), "strictly increasing"),
    ],
)
def test_tracking_measurement_reports_missing_or_inconsistent_metadata(mutation, match):
    track = track_metadata_fixture()
    args = measurement_kwargs()
    mutation(track, args)
    with pytest.raises(ValueError, match=match):
        track.to_measurement(**args)


def test_synthetic_video_is_explicit_and_cannot_be_labelled_as_rig_measurement():
    track = track_metadata_fixture()
    track.synthetic = True
    track.camera_calibration = None
    args = measurement_kwargs()
    with pytest.raises(ValueError, match="source='simulator'"):
        track.to_measurement(**args)
    args["provenance"]["source"] = "simulator"
    assert track.to_measurement(**args)["synthetic"] is True


def test_frame_sequence_without_timing_is_rejected_instead_of_assuming_30_fps():
    with pytest.raises(ValueError, match="fps is required"):
        track_keypoints([np.zeros((20, 20), dtype=np.uint8)], {"hip": 7}, 20.0)

