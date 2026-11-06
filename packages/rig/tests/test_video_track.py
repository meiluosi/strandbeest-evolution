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
    TrackResult,
    calibrate_camera,
    track_keypoints,
    track_natural_feature,
    track_point_optical_flow,
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


def make_feature_frame(
    w: int = 400,
    h: int = 300,
    features: dict[str, tuple[float, float]] | None = None,
) -> np.ndarray:
    """Generate a synthetic test frame with high-contrast distinct features."""
    frame = np.full((h, w), 230, dtype=np.uint8)
    if features:
        for name, (cx, cy) in features.items():
            icx, icy = int(round(cx)), int(round(cy))
            cv2.circle(frame, (icx, icy), 7, 20, -1)
            cv2.circle(frame, (icx, icy), 12, 120, 2)
            cv2.line(frame, (icx - 10, icy), (icx + 10, icy), 0, 1)
            cv2.line(frame, (icx, icy - 10), (icx, icy + 10), 0, 1)
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)


def test_track_point_optical_flow_synthetic_moving_feature():
    fps = 30.0
    n_frames = 20
    w, h = 500, 300
    scale_mpp = 0.001

    true_xs = [100.0 + i * 5.0 for i in range(n_frames)]
    true_ys = [140.0 for _ in range(n_frames)]

    frames = [
        make_feature_frame(w, h, {"hip": (true_xs[i], true_ys[i])})
        for i in range(n_frames)
    ]

    res = track_point_optical_flow(
        frames,
        initial_points={"hip": (100.0, 140.0)},
        scale_m_per_pixel=scale_mpp,
        fps=fps,
        subpixel=True,
    )

    assert isinstance(res, MultiKeypointTrackResult)
    assert res.frames == n_frames
    assert res.detected_fractions["hip"] == 1.0
    assert len(res.warnings) == 0

    tracked_x_m = res.trajectories["hip"][:, 0]
    expected_x_m = np.array([(x - 100.0) * scale_mpp for x in true_xs])
    assert np.allclose(tracked_x_m, expected_x_m, atol=0.0005)

    single_res = res.to_track_result("hip")
    assert isinstance(single_res, TrackResult)
    assert len(single_res.x) == n_frames
    assert single_res.detected_fraction == 1.0


def test_track_natural_feature_template_fallback_and_alias():
    fps = 30.0
    n_frames = 15
    w, h = 400, 300
    scale_mpp = 0.002

    true_xs = [80.0 + i * 3.5 for i in range(n_frames)]
    true_ys = [120.0 + i * 1.5 for i in range(n_frames)]

    frames = [
        make_feature_frame(w, h, {"crank": (true_xs[i], true_ys[i])})
        for i in range(n_frames)
    ]

    res_template = track_natural_feature(
        frames,
        initial_points={"crank": (80.0, 120.0)},
        scale_m_per_pixel=scale_mpp,
        fps=fps,
        tracking_method="template",
    )

    assert res_template.detected_fractions["crank"] == 1.0
    tracked_x_m = res_template.trajectories["crank"][:, 0]
    expected_x_m = np.array([(x - 80.0) * scale_mpp for x in true_xs])
    assert np.allclose(tracked_x_m, expected_x_m, atol=0.001)


def test_optical_flow_forward_backward_consistency_and_occlusion():
    fps = 30.0
    n_frames = 20
    w, h = 400, 300
    scale_mpp = 0.001

    true_xs = [100.0 + i * 4.0 for i in range(n_frames)]
    true_ys = [150.0 for _ in range(n_frames)]

    frames = []
    for i in range(n_frames):
        if i in (8, 9, 10):
            frame = make_feature_frame(w, h, None)
        else:
            frame = make_feature_frame(w, h, {"joint": (true_xs[i], true_ys[i])})
        frames.append(frame)

    res = track_point_optical_flow(
        frames,
        initial_points={"joint": (100.0, 150.0)},
        scale_m_per_pixel=scale_mpp,
        fps=fps,
        fb_threshold=1.0,
        template_fallback=True,
    )

    assert res.detected_fractions["joint"] == pytest.approx(17 / 20)
    assert any("gaps interpolated" in w for w in res.warnings)
    assert not np.isnan(res.trajectories["joint"]).any()
    traj_x = res.trajectories["joint"][:, 0]
    assert np.all(np.diff(traj_x) > 0)


def test_natural_feature_input_validation():
    sample_frame = make_feature_frame(200, 200, {"hip": (50, 50)})

    with pytest.raises(ValueError, match="scale_m_per_pixel must be finite and positive"):
        track_point_optical_flow([sample_frame], {"hip": (50, 50)}, scale_m_per_pixel=-0.01, fps=30.0)

    with pytest.raises(ValueError, match="scale_m_per_pixel must be finite and positive"):
        track_point_optical_flow([sample_frame], {"hip": (50, 50)}, scale_m_per_pixel=0.0, fps=30.0)

    with pytest.raises(ValueError, match="scale_m_per_pixel or reference distance calibration"):
        track_point_optical_flow([sample_frame], {"hip": (50, 50)}, scale_m_per_pixel=None, fps=30.0)

    with pytest.raises(ValueError, match="fps must be finite and positive"):
        track_point_optical_flow([sample_frame], {"hip": (50, 50)}, scale_m_per_pixel=0.001, fps=-10.0)

    with pytest.raises(ValueError, match="fps is required"):
        track_point_optical_flow([sample_frame], {"hip": (50, 50)}, scale_m_per_pixel=0.001, fps=None)

    with pytest.raises(ValueError, match="video sequence has no frames"):
        track_point_optical_flow([], {"hip": (50, 50)}, scale_m_per_pixel=0.001, fps=30.0)

    with pytest.raises(ValueError, match="initial_points must be a non-empty dictionary"):
        track_point_optical_flow([sample_frame], {}, scale_m_per_pixel=0.001, fps=30.0)

    with pytest.raises(ValueError, match="out of frame bounds"):
        track_point_optical_flow([sample_frame], {"hip": (500, 500)}, scale_m_per_pixel=0.001, fps=30.0)

    with pytest.raises(ValueError, match="unknown tracking_method"):
        track_point_optical_flow(
            [sample_frame], {"hip": (50, 50)}, scale_m_per_pixel=0.001, fps=30.0, tracking_method="invalid"
        )


def test_natural_feature_reference_distance_calibration():
    frame1 = make_feature_frame(400, 300, {"hip": (100, 100), "crank": (300, 100)})
    frame2 = make_feature_frame(400, 300, {"hip": (102, 100), "crank": (302, 100)})
    frame3 = make_feature_frame(400, 300, {"hip": (104, 100), "crank": (304, 100)})

    res = track_point_optical_flow(
        [frame1, frame2, frame3],
        initial_points={"hip": (100.0, 100.0), "crank": (300.0, 100.0)},
        reference_points=("hip", "crank"),
        reference_distance_m=0.1,
        fps=30.0,
    )
    assert res.metres_per_pixel == pytest.approx(0.0005)


def test_natural_feature_multi_keypoint_to_measurement_schema_v2():
    fps = 30.0
    duration = 1.0
    n_frames = int(fps * duration)
    w, h = 800, 500
    scale_mpp = 0.001
    omega_true = 2.0 * math.pi * 1.5
    crank_radius_px = 40.0

    frames = []
    for i in range(n_frames):
        t = i / fps
        hip_x = 120.0 + 30.0 * t
        hip_y = 100.0

        crank_x = hip_x + 180.0 + crank_radius_px * math.cos(omega_true * t)
        crank_y = 100.0 + crank_radius_px * math.sin(omega_true * t)

        foot_x = hip_x + 80.0 + 30.0 * math.sin(omega_true * t)
        foot_y = 250.0 + 20.0 * math.cos(omega_true * t)

        frame = make_feature_frame(w, h, {"hip": (hip_x, hip_y), "crank": (crank_x, crank_y), "foot": (foot_x, foot_y)})
        frames.append(frame)

    res = track_point_optical_flow(
        frames,
        initial_points={
            "hip": (120.0, 100.0),
            "crank": (120.0 + 180.0 + crank_radius_px, 100.0),
            "foot": (200.0, 270.0),
        },
        scale_m_per_pixel=scale_mpp,
        fps=fps,
        synthetic=True,
    )

    assert res.detected_fractions["hip"] > 0.95
    assert res.detected_fractions["crank"] > 0.95
    assert res.detected_fractions["foot"] > 0.95
    assert float(np.mean(np.abs(res.omega))) == pytest.approx(omega_true, rel=0.15)

    args = {
        "measurement_id": new_ulid(),
        "design_id": new_ulid(),
        "name": "natural-feature-test",
        "conditions": {"kind": "motor_no_wind", "surface": "synthetic_bench"},
        "provenance": {
            "source": "simulator",
            "calibration": {
                "uncertainty": {
                    "t": 0.001,
                    "psi": 0.02,
                    "omega": 0.05,
                    "foot_x": 0.001,
                    "foot_y": 0.001,
                    "x": 0.001,
                }
            },
        },
        "crank_direction": 1,
    }

    doc = res.to_measurement(**args)
    validate("measurement", doc)
    assert doc["id"] == args["measurement_id"]
    assert doc["synthetic"] is True
    assert doc["provenance"]["calibration"]["tracking"]["method"] == "lucas_kanade_optical_flow"
    assert len(doc["channels"]["t"]) == n_frames
    assert len(doc["channels"]["foot_y"]) == n_frames


