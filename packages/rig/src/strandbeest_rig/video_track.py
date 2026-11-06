"""Track an ArUco marker in a side-view video to get the body's forward position x(t) in metres.

Assumptions (state them in your lab notebook): the camera looks perpendicular to the direction of travel, the marker is flat
on the body facing the camera and sits roughly in the plane of motion, and the camera does not move. Perspective error grows
with the angle; use a long lens or a distant camera.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator

from strandbeest_common.schemas import validate


@dataclass
class TrackResult:
    t: np.ndarray  # seconds from the first frame
    x: np.ndarray  # metres, forward positive, zero at the first detection
    fps: float
    frames: int
    detected_fraction: float
    metres_per_pixel: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class CameraIntrinsics:
    """Pinhole camera intrinsic parameters and distortion coefficients."""

    camera_matrix: np.ndarray  # 3x3 float64 camera matrix
    dist_coeffs: np.ndarray  # distortion coefficients (1, 5) or (5,) float64
    image_size: tuple[int, int] = (0, 0)  # (width, height)
    reprojection_error: float = 0.0

    def undistort_points(self, points: np.ndarray) -> np.ndarray:
        """Undistort 2D pixel coordinates (N, 2) with sub-pixel camera calibration."""
        import cv2

        pts = np.asarray(points, dtype=np.float32)
        orig_shape = pts.shape
        pts_flat = pts.reshape(-1, 1, 2)
        undistorted = cv2.undistortPoints(pts_flat, self.camera_matrix, self.dist_coeffs, P=self.camera_matrix)
        return undistorted.reshape(orig_shape)

    def undistort_image(self, image: np.ndarray) -> np.ndarray:
        """Undistort an entire image frame."""
        import cv2

        return cv2.undistort(image, self.camera_matrix, self.dist_coeffs)


def calibrate_camera(
    images: list[np.ndarray],
    board_size: tuple[int, int] = (9, 6),
    square_size_mm: float = 25.0,
) -> CameraIntrinsics:
    """Calibrate camera intrinsics from checkerboard calibration images.

    Args:
        images: list of BGR or grayscale images showing a planar checkerboard.
        board_size: (columns, rows) of inner checkerboard corners.
        square_size_mm: physical edge length of one checkerboard square in millimetres.
    """
    import cv2

    objp = np.zeros((board_size[1] * board_size[0], 3), np.float32)
    objp[:, :2] = np.mgrid[0 : board_size[0], 0 : board_size[1]].T.reshape(-1, 2) * (square_size_mm / 1000.0)

    objpoints = []
    imgpoints = []
    h, w = 0, 0

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    for img in images:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        h, w = gray.shape[:2]
        found, corners = cv2.findChessboardCorners(gray, board_size, None)
        if found:
            corners_sub = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            objpoints.append(objp)
            imgpoints.append(corners_sub)

    if not objpoints:
        raise ValueError(f"no checkerboards detected with inner corner grid size {board_size}")

    ret, mtx, dist, _, _ = cv2.calibrateCamera(objpoints, imgpoints, (w, h), None, None)
    return CameraIntrinsics(
        camera_matrix=mtx,
        dist_coeffs=dist,
        image_size=(w, h),
        reprojection_error=float(ret),
    )


@dataclass
class MultiKeypointTrackResult:
    """Multi-keypoint tracking results: trajectories, crank velocity, and foot curves."""

    t: np.ndarray  # seconds from first frame (N,)
    trajectories: dict[str, np.ndarray]  # keypoint -> (N, 2) [x, y] in metres
    omega: np.ndarray  # (N,) instantaneous crank angular velocity (rad/s)
    foot_path: np.ndarray  # (N, 2) foot position relative to hip in metres [x_foot - x_hip, y_foot - y_hip]
    crank_angle: np.ndarray  # (N,) unwrapped crank angle theta(t) in radians
    fps: float
    frames: int
    detected_fractions: dict[str, float]
    metres_per_pixel: float
    warnings: list[str] = field(default_factory=list)
    synthetic: bool | None = None  # Unknown until explicitly declared by the caller.
    raw_source: str | None = None
    camera_calibration: dict[str, Any] | None = None
    tracking_metadata: dict[str, Any] = field(default_factory=dict)

    def to_measurement(
        self,
        *,
        measurement_id: str,
        design_id: str,
        name: str,
        conditions: dict[str, Any],
        provenance: dict[str, Any],
        crank_direction: int,
        alignment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Materialize a Measurement asset with explicit identity and video provenance.

        ``crank_direction`` maps the observed counterclockwise angle to positive
        rotation in the walking direction. Uncertainty values are absolute 1-sigma
        errors in the channel units, supplied by the experimenter, never guessed
        from reprojection error. The caller stores the returned asset before using
        its id in a Profile; tracking alone does not establish physical validation.
        """
        if not isinstance(self.synthetic, bool):
            raise ValueError("declare synthetic=True or False when tracking the video")
        if crank_direction not in (-1, 1) or isinstance(crank_direction, bool):
            raise ValueError("crank_direction must be +1 or -1")
        if not {"hip", "foot"} <= self.trajectories.keys() or not any(
            key in self.trajectories for key in ("crank", "crank_pin")
        ):
            raise ValueError("digital-twin Measurement requires tracked hip, foot and crank markers")
        t = np.asarray(self.t, dtype=float)
        if t.ndim != 1 or len(t) < 2 or not np.isfinite(t).all() or not np.all(np.diff(t) > 0):
            raise ValueError("tracking timestamps must be finite and strictly increasing")
        arrays = {
            "t": t,
            "psi": crank_direction * (self.crank_angle - self.crank_angle[0]),
            "omega": crank_direction * self.omega,
            "foot_x": self.foot_path[:, 0],
            "foot_y": self.foot_path[:, 1],
            "x": self.trajectories["hip"][:, 0],
        }
        if any(np.shape(a) != t.shape or not np.isfinite(a).all() for a in arrays.values()):
            raise ValueError("tracking channels must be finite equal-length arrays")
        prov = copy.deepcopy(provenance)
        cal = prov.setdefault("calibration", {})
        if self.raw_source and not prov.get("raw_file"):
            prov["raw_file"] = self.raw_source
        if self.camera_calibration is not None:
            cal["camera"] = copy.deepcopy(self.camera_calibration)
        if alignment is not None:
            cal["alignment"] = copy.deepcopy(alignment)
        cal["tracking"] = {
            **copy.deepcopy(self.tracking_metadata),
            "detected_fractions": dict(self.detected_fractions),
            "metres_per_pixel": self.metres_per_pixel,
            "fps": self.fps,
            "frames": self.frames,
            "crank_direction": crank_direction,
            "observed_crank_zero_rad": float(self.crank_angle[0]),
            "coordinates": "foot relative to hip; x forward, y up; hip x relative to first frame",
        }
        units = {"t": "s", "psi": "rad", "omega": "rad/s", "foot_x": "m", "foot_y": "m", "x": "m"}
        stated_units = cal.get("units", {})
        if any(key in stated_units and stated_units[key] != unit for key, unit in units.items()):
            raise ValueError("tracking output units are s, rad, rad/s and m; stated units disagree")
        cal["units"] = {**stated_units, **units}
        uncertainty = cal.get("uncertainty", {})
        missing = [key for key in units if not isinstance(uncertainty.get(key), (int, float))
                   or isinstance(uncertainty.get(key), bool) or not np.isfinite(uncertainty[key]) or uncertainty[key] <= 0]
        if missing:
            raise ValueError(f"positive absolute 1-sigma uncertainty required for channels: {', '.join(missing)}")
        cal["uncertainty_kind"] = "absolute_1sigma"
        if self.synthetic:
            if prov.get("source") != "simulator":
                raise ValueError("synthetic tracking requires provenance.source='simulator'")
        else:
            missing = [f"calibration.{key}" for key in ("instrument", "measured_on", "calibrated_on", "camera") if not cal.get(key)]
            if not prov.get("raw_file"):
                missing.append("raw_file")
            if prov.get("source") not in ("rig", "manual"):
                missing.append("source (rig or manual)")
            if missing:
                raise ValueError(f"real video provenance missing: {', '.join(missing)}")
            for key in ("measured_on", "calibrated_on"):
                date.fromisoformat(cal[key])
            camera = cal["camera"]
            matrix = np.asarray(camera.get("camera_matrix", []), dtype=float)
            size = np.asarray(camera.get("image_size", []))
            distortion = np.asarray(camera.get("dist_coeffs", []), dtype=float)
            if (matrix.shape != (3, 3) or not np.isfinite(matrix).all() or np.linalg.det(matrix) == 0
                    or size.shape != (2,) or not np.all(size > 0) or not distortion.size or not np.isfinite(distortion).all()):
                raise ValueError("camera calibration needs a finite nonsingular 3x3 matrix, distortion coefficients and image size")
        doc = {
            "schema_version": 2,
            "id": measurement_id,
            "design_id": design_id,
            "name": name,
            "synthetic": self.synthetic,
            "conditions": copy.deepcopy(conditions),
            "channels": {key: np.asarray(value).tolist() for key, value in arrays.items()},
            "provenance": prov,
            "quality": {
                "sample_rate_hz": float(self.fps),
                "duration_s": float(t[-1] - t[0]),
                "warnings": list(self.warnings),
            },
        }
        validate("measurement", doc)
        return doc

    def sample_foot_curve(self, num_points: int = 100) -> tuple[np.ndarray, np.ndarray]:
        """Sub-pixel interpolated foot curve (x, y) parameterized over crank angle [0, 2*pi)."""
        if len(self.crank_angle) < 4 or np.all(self.foot_path == 0):
            th = np.linspace(0, 2 * np.pi, num_points, endpoint=False)
            return np.zeros(num_points), np.zeros(num_points)

        theta_mod = np.mod(self.crank_angle, 2 * np.pi)
        order = np.argsort(theta_mod)
        th_sorted = theta_mod[order]
        fx_sorted = self.foot_path[order, 0]
        fy_sorted = self.foot_path[order, 1]

        # Filter out identical or extremely close angles for strict spline monotonicity
        keep = np.insert(np.diff(th_sorted) > 1e-5, 0, True)
        th_s = th_sorted[keep]
        fx_s = fx_sorted[keep]
        fy_s = fy_sorted[keep]

        if len(th_s) < 4:
            th = np.linspace(0, 2 * np.pi, num_points, endpoint=False)
            return np.interp(th, th_s, fx_s), np.interp(th, th_s, fy_s)

        # Extend periodic wrap-around
        th_ext = np.concatenate([th_s - 2 * np.pi, th_s, th_s + 2 * np.pi])
        fx_ext = np.concatenate([fx_s, fx_s, fx_s])
        fy_ext = np.concatenate([fy_s, fy_s, fy_s])

        query = np.linspace(0, 2 * np.pi, num_points, endpoint=False)
        spl_x = CubicSpline(th_ext, fx_ext)
        spl_y = CubicSpline(th_ext, fy_ext)
        return spl_x(query), spl_y(query)

    def to_track_result(self, keypoint: str | None = None) -> TrackResult:
        """Extract a single-keypoint forward position TrackResult for backward compatibility."""
        key = keypoint if keypoint is not None else ("hip" if "hip" in self.trajectories else next(iter(self.trajectories)))
        if key not in self.trajectories:
            raise KeyError(f"keypoint '{key}' not in trajectories")
        return TrackResult(
            t=self.t,
            x=self.trajectories[key][:, 0],
            fps=self.fps,
            frames=self.frames,
            detected_fraction=self.detected_fractions.get(key, 1.0),
            metres_per_pixel=self.metres_per_pixel,
            warnings=list(self.warnings),
        )


def _subpixel_interp(full_idx: np.ndarray, known_idx: np.ndarray, vals: np.ndarray) -> np.ndarray:
    """Interpolate time series with sub-pixel cubic spline or PCHIP where possible."""
    if len(known_idx) == len(full_idx):
        return vals.copy()
    if len(known_idx) >= 4:
        try:
            return PchipInterpolator(known_idx, vals)(full_idx)
        except Exception:
            return np.interp(full_idx, known_idx, vals)
    return np.interp(full_idx, known_idx, vals)


def _load_video_frames(
    video_source: str | Path | Sequence[np.ndarray],
    fps: float | None,
) -> tuple[list[np.ndarray], float, str]:
    """Load video frames and extract or validate video framerate."""
    import cv2

    if fps is not None and (
        not isinstance(fps, (int, float)) or isinstance(fps, bool) or not np.isfinite(fps) or fps <= 0
    ):
        raise ValueError("fps must be finite and positive")
    video_fps = float(fps) if fps is not None else None
    frame_rate_source = "caller" if fps is not None else "video_container"

    frames_list: list[np.ndarray] = []
    if isinstance(video_source, (list, tuple)):
        frames_list = list(video_source)
        if not frames_list:
            raise ValueError("video sequence has no frames")
        if video_fps is None:
            raise ValueError("fps is required for a frame sequence; video timing must not be guessed")
    else:
        cap = cv2.VideoCapture(str(video_source))
        if not cap.isOpened():
            raise FileNotFoundError(f"cannot open video {video_source}")
        video_fps = float(fps) if fps is not None else float(cap.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(video_fps) or video_fps <= 0:
            cap.release()
            raise ValueError("video has no valid frame rate; supply a measured fps")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames_list.append(frame)
        cap.release()
        if not frames_list:
            raise ValueError("video has no frames")

    return frames_list, video_fps, frame_rate_source


def _compute_trajectories_and_kinematics(
    clean_coords: dict[str, np.ndarray],
    metres_per_pixel: float,
    t: np.ndarray,
    n_frames: int,
    forward_is_left: bool,
) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, np.ndarray]:
    """Compute physical trajectories, crank angular velocity omega(t), and foot path from pixel coordinates."""
    if "hip" in clean_coords:
        origin_u, origin_v = clean_coords["hip"][0]
    elif "crank_pivot" in clean_coords:
        origin_u, origin_v = clean_coords["crank_pivot"][0]
    else:
        first_key = next(iter(clean_coords))
        origin_u, origin_v = clean_coords[first_key][0]

    sign_x = -1.0 if forward_is_left else 1.0
    trajectories: dict[str, np.ndarray] = {}
    for name, uv in clean_coords.items():
        x_m = (uv[:, 0] - origin_u) * metres_per_pixel * sign_x
        y_m = -(uv[:, 1] - origin_v) * metres_per_pixel
        trajectories[name] = np.column_stack([x_m, y_m])

    crank_key = "crank" if "crank" in trajectories else ("crank_pin" if "crank_pin" in trajectories else None)
    pivot_key = "crank_pivot" if "crank_pivot" in trajectories else None

    if crank_key and pivot_key:
        rx = trajectories[crank_key][:, 0] - trajectories[pivot_key][:, 0]
        ry = trajectories[crank_key][:, 1] - trajectories[pivot_key][:, 1]
    elif crank_key and "hip" in trajectories:
        r_rel = trajectories[crank_key] - trajectories["hip"]
        A = np.column_stack([2 * r_rel[:, 0], 2 * r_rel[:, 1], np.ones(len(r_rel))])
        b = r_rel[:, 0] ** 2 + r_rel[:, 1] ** 2
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        rx = r_rel[:, 0] - sol[0]
        ry = r_rel[:, 1] - sol[1]
    elif crank_key:
        crank_pts = trajectories[crank_key]
        A = np.column_stack([2 * crank_pts[:, 0], 2 * crank_pts[:, 1], np.ones(len(crank_pts))])
        b = crank_pts[:, 0] ** 2 + crank_pts[:, 1] ** 2
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        rx = crank_pts[:, 0] - sol[0]
        ry = crank_pts[:, 1] - sol[1]
    else:
        rx = np.zeros(n_frames)
        ry = np.zeros(n_frames)

    if crank_key and len(t) >= 4:
        theta_raw = np.arctan2(ry, rx)
        crank_angle = np.unwrap(theta_raw)
        spl_theta = CubicSpline(t, crank_angle)
        omega = spl_theta.derivative()(t)
    elif crank_key and len(t) >= 2:
        theta_raw = np.arctan2(ry, rx)
        crank_angle = np.unwrap(theta_raw)
        omega = np.gradient(crank_angle, t)
    else:
        crank_angle = np.zeros(n_frames)
        omega = np.zeros(n_frames)

    if "foot" in trajectories and "hip" in trajectories:
        foot_path = trajectories["foot"] - trajectories["hip"]
    elif "foot" in trajectories:
        foot_path = trajectories["foot"] - trajectories["foot"][0:1]
    else:
        foot_path = np.zeros((n_frames, 2))

    return trajectories, omega, foot_path, crank_angle


def _subpixel_peak_fit(res: np.ndarray, max_loc: tuple[int, int]) -> tuple[float, float]:
    """Fit a local parabolic peak around the integer maximum in normalized correlation score map."""
    px, py = max_loc
    h, w = res.shape[:2]
    dx = 0.0
    dy = 0.0

    if 0 < px < w - 1:
        denom_x = float(res[py, px - 1] - 2.0 * res[py, px] + res[py, px + 1])
        if abs(denom_x) > 1e-6:
            shift_x = (float(res[py, px - 1]) - float(res[py, px + 1])) / (2.0 * denom_x)
            if -1.0 <= shift_x <= 1.0:
                dx = shift_x

    if 0 < py < h - 1:
        denom_y = float(res[py - 1, px] - 2.0 * res[py, px] + res[py + 1, px])
        if abs(denom_y) > 1e-6:
            shift_y = (float(res[py - 1, px]) - float(res[py + 1, px])) / (2.0 * denom_y)
            if -1.0 <= shift_y <= 1.0:
                dy = shift_y

    return float(px + dx), float(py + dy)


def _resolve_scale(
    scale_m_per_pixel: float | None,
    reference_distance_m: float | None,
    reference_points: tuple[str, str] | Sequence[str] | None,
    initial_points: dict[str, tuple[float, float]],
) -> float:
    """Resolve scale in metres per pixel from explicit scale or reference distance calibration."""
    if scale_m_per_pixel is not None:
        if (
            not isinstance(scale_m_per_pixel, (int, float))
            or isinstance(scale_m_per_pixel, bool)
            or not np.isfinite(scale_m_per_pixel)
            or scale_m_per_pixel <= 0
        ):
            raise ValueError("scale_m_per_pixel must be finite and positive")
        return float(scale_m_per_pixel)

    if reference_distance_m is not None:
        if (
            not isinstance(reference_distance_m, (int, float))
            or isinstance(reference_distance_m, bool)
            or not np.isfinite(reference_distance_m)
            or reference_distance_m <= 0
        ):
            raise ValueError("reference_distance_m must be finite and positive")
        if reference_points is None or len(reference_points) != 2:
            raise ValueError("reference_distance_m requires reference_points pair (e.g. ('hip', 'crank'))")
        p1, p2 = reference_points[0], reference_points[1]
        if p1 not in initial_points or p2 not in initial_points:
            raise ValueError(f"reference_points ('{p1}', '{p2}') must both be present in initial_points")
        pt1 = initial_points[p1]
        pt2 = initial_points[p2]
        dist_px = float(np.hypot(pt1[0] - pt2[0], pt1[1] - pt2[1]))
        if dist_px <= 0:
            raise ValueError(f"reference_points '{p1}' and '{p2}' have zero pixel separation")
        return float(reference_distance_m) / dist_px

    raise ValueError("scale_m_per_pixel or reference distance calibration (reference_distance_m and reference_points) must be provided")


def track_keypoints(
    video_source: str | Path | Sequence[np.ndarray],
    marker_ids: dict[str, int],
    marker_mm: float,
    *,
    fps: float | None = None,
    dictionary: str = "DICT_4X4_50",
    forward_is_left: bool = False,
    intrinsics: CameraIntrinsics | None = None,
    subpixel: bool = True,
    synthetic: bool | None = None,
    raw_source: str | None = None,
) -> MultiKeypointTrackResult:
    """Track multi-keypoint markers (e.g. hip, crank pivot, crank, foot) simultaneously over time.

    Computes tracked kinematic trajectories, instantaneous crank angular velocity omega(t),
    and foot path curves with sub-pixel interpolation.

    Args:
        video_source: Path to video file, or sequence of image frames (BGR / Grayscale).
        marker_ids: Dictionary mapping keypoint names to ArUco marker IDs (e.g. {"hip": 0, "crank": 1, "foot": 2}).
        marker_mm: Physical edge width of the square ArUco marker in millimetres.
        fps: Video framerate (if None and reading video file, retrieved from container).
        dictionary: OpenCV ArUco predefined dictionary name.
        forward_is_left: True if forward direction corresponds to negative image u-axis.
        intrinsics: Optional CameraIntrinsics for lens undistortion and camera calibration.
        subpixel: True to refine marker corner locations with sub-pixel interpolation.
        synthetic: Explicitly declare rendered footage or physical footage; None retains unknown provenance.
        raw_source: Source video identifier/path, required when materializing physical frame sequences.
    """
    import cv2

    if not np.isfinite(marker_mm) or marker_mm <= 0:
        raise ValueError("marker_mm must be finite and positive")
    frames_list, video_fps, frame_rate_source = _load_video_frames(video_source, fps)
    n_frames = len(frames_list)
    det_params = cv2.aruco.DetectorParameters()
    if subpixel:
        det_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        det_params.cornerRefinementWinSize = 5
        det_params.cornerRefinementMaxIterations = 30
        det_params.cornerRefinementMinAccuracy = 0.05

    det = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary)),
        det_params,
    )

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.05)

    raw_coords: dict[str, list[tuple[float, float]]] = {name: [] for name in marker_ids}
    sides: list[float] = []

    for frame in frames_list:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        corners, ids, _ = det.detectMarkers(gray)

        frame_detections: dict[int, np.ndarray] = {}
        if ids is not None and len(corners) > 0:
            for c, mid in zip(corners, ids.flatten()):
                pts = c.reshape(4, 2).astype(np.float32)
                if subpixel:
                    try:
                        pts = cv2.cornerSubPix(gray, pts.reshape(-1, 1, 2), (5, 5), (-1, -1), criteria).reshape(4, 2)
                    except Exception:
                        pass
                if intrinsics is not None:
                    pts = intrinsics.undistort_points(pts)

                frame_detections[int(mid)] = pts
                side_len = float(np.mean([np.linalg.norm(pts[k] - pts[(k + 1) % 4]) for k in range(4)]))
                sides.append(side_len)

        for name, mid in marker_ids.items():
            if mid in frame_detections:
                p = frame_detections[mid]
                raw_coords[name].append((float(p[:, 0].mean()), float(p[:, 1].mean())))
            else:
                raw_coords[name].append((float("nan"), float("nan")))

    if not sides:
        raise ValueError(f"no markers from {marker_ids} detected in video")

    metres_per_pixel = (marker_mm / 1000.0) / float(np.median(sides))
    frames_idx = np.arange(n_frames)
    t = frames_idx / video_fps

    detected_fractions: dict[str, float] = {}
    clean_coords: dict[str, np.ndarray] = {}

    for name, pts_list in raw_coords.items():
        arr = np.array(pts_list)
        u, v = arr[:, 0], arr[:, 1]
        found = ~np.isnan(u)
        frac = float(found.mean())
        detected_fractions[name] = frac
        if found.sum() < 3:
            raise ValueError(
                f"marker '{name}' (id {marker_ids[name]}) found in only {int(found.sum())} of {n_frames} frames"
            )
        u_interp = _subpixel_interp(frames_idx, frames_idx[found], u[found])
        v_interp = _subpixel_interp(frames_idx, frames_idx[found], v[found])
        clean_coords[name] = np.column_stack([u_interp, v_interp])

    trajectories, omega, foot_path, crank_angle = _compute_trajectories_and_kinematics(
        clean_coords=clean_coords,
        metres_per_pixel=metres_per_pixel,
        t=t,
        n_frames=n_frames,
        forward_is_left=forward_is_left,
    )

    warnings: list[str] = []
    for name, frac in detected_fractions.items():
        if frac < 0.9:
            warnings.append(f"marker '{name}' detected in only {frac * 100:.0f} % of frames; gaps interpolated")
    if video_fps < 25:
        warnings.append(f"video is {video_fps:.0f} fps; temporal resolution is coarse")

    return MultiKeypointTrackResult(
        t=t,
        trajectories=trajectories,
        omega=omega,
        foot_path=foot_path,
        crank_angle=crank_angle,
        fps=video_fps,
        frames=n_frames,
        detected_fractions=detected_fractions,
        metres_per_pixel=metres_per_pixel,
        warnings=warnings,
        synthetic=synthetic,
        raw_source=raw_source or (str(video_source) if isinstance(video_source, (str, Path)) else None),
        camera_calibration={
            "camera_matrix": intrinsics.camera_matrix.tolist(),
            "dist_coeffs": intrinsics.dist_coeffs.tolist(),
            "image_size": list(intrinsics.image_size),
            "reprojection_error_px": intrinsics.reprojection_error,
        } if intrinsics is not None else None,
        tracking_metadata={
            "marker_ids": dict(marker_ids), "marker_mm": marker_mm,
            "dictionary": dictionary, "forward_is_left": forward_is_left, "subpixel": subpixel,
            "frame_rate_source": frame_rate_source, "first_frame_index": 0,
        },
    )


def track_marker(
    video_path: str,
    marker_id: int,
    marker_mm: float,
    *,
    dictionary: str = "DICT_4X4_50",
    forward_is_left: bool = False,
) -> TrackResult:
    import cv2  # optional dependency: pip install "strandbeest-rig[video]"

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary)), cv2.aruco.DetectorParameters())
    us: list[float] = []
    sides: list[float] = []
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = det.detectMarkers(gray)
        u = float("nan")
        if ids is not None:
            for c, i in zip(corners, ids.flatten()):
                if int(i) == marker_id:
                    pts = c.reshape(4, 2)
                    u = float(pts[:, 0].mean())
                    sides.append(float(np.mean([np.linalg.norm(pts[k] - pts[(k + 1) % 4]) for k in range(4)])))
        us.append(u)
        n += 1
    cap.release()
    if n == 0:
        raise ValueError("video has no frames")
    u = np.array(us)
    found = ~np.isnan(u)
    if found.sum() < 5:
        raise ValueError(f"marker id {marker_id} found in only {int(found.sum())} of {n} frames; check the id, dictionary and lighting")
    mpp = (marker_mm / 1000.0) / float(np.median(sides))
    frames_idx = np.arange(n)
    u_full = np.interp(frames_idx, frames_idx[found], u[found])
    x = (u_full - u_full[np.argmax(found)]) * mpp * (-1.0 if forward_is_left else 1.0)
    frac = float(found.mean())
    warnings = []
    if frac < 0.9:
        warnings.append(f"marker detected in only {frac * 100:.0f} % of frames; gaps were interpolated linearly")
    if fps < 25:
        warnings.append(f"video is {fps:.0f} fps; position resolution in time is coarse")
    return TrackResult(frames_idx / fps, x, fps, n, frac, mpp, warnings)


def track_point_optical_flow(
    video_source: str | Path | Sequence[np.ndarray],
    initial_points: dict[str, tuple[float, float] | Sequence[float] | np.ndarray],
    scale_m_per_pixel: float | None = None,
    *,
    fps: float | None = None,
    forward_is_left: bool = False,
    intrinsics: CameraIntrinsics | None = None,
    subpixel: bool = True,
    fb_threshold: float = 1.0,
    template_fallback: bool = True,
    template_size: int = 21,
    search_window: int = 41,
    min_correlation: float = 0.5,
    tracking_method: str = "optical_flow",
    reference_points: tuple[str, str] | Sequence[str] | None = None,
    reference_distance_m: float | None = None,
    synthetic: bool | None = None,
    raw_source: str | None = None,
) -> MultiKeypointTrackResult:
    """Track natural/markerless features using Lucas-Kanade optical flow and template matching.

    Supports subpixel refinement, bidirectional forward-backward consistency filtering to detect
    occlusion or tracking drift, and fallback to normalized cross-correlation template matching
    with sub-pixel parabolic peak fitting.

    Args:
        video_source: Path to video file, or sequence of image frames (BGR / Grayscale).
        initial_points: Mapping of keypoint names to initial (u, v) pixel coordinates in frame 0.
        scale_m_per_pixel: Physical calibration in metres per pixel (positive float).
        fps: Video framerate (required if passing a frame sequence).
        forward_is_left: True if forward walking direction corresponds to negative image u-axis.
        intrinsics: Optional CameraIntrinsics for lens undistortion and camera calibration.
        subpixel: True to refine initial positions and tracks with sub-pixel interpolation.
        fb_threshold: Maximum bidirectional forward-backward error in pixels to accept an LK track.
        template_fallback: True to fall back to template matching when optical flow is lost or occluded.
        template_size: Patch width/height in pixels for template matching and initial feature extraction.
        search_window: Search window width/height in pixels for template matching fallback.
        min_correlation: Minimum normalized cross-correlation score (0 to 1) required to accept template match.
        tracking_method: "optical_flow" for LK flow with template fallback, or "template" for pure template matching.
        reference_points: Optional pair of keypoint names for scale calibration if scale_m_per_pixel is omitted.
        reference_distance_m: Known physical distance in metres between reference_points.
        synthetic: True for simulator rendered footage, False for physical test rig footage.
        raw_source: Source video identifier/path for provenance.
    """
    import cv2

    if tracking_method not in ("optical_flow", "template"):
        raise ValueError(f"unknown tracking_method '{tracking_method}', expected 'optical_flow' or 'template'")
    if fb_threshold <= 0 or not np.isfinite(fb_threshold):
        raise ValueError("fb_threshold must be finite and positive")
    if template_size < 3:
        raise ValueError("template_size must be >= 3")
    if search_window < template_size:
        raise ValueError("search_window must be >= template_size")
    if not (0.0 < min_correlation <= 1.0):
        raise ValueError("min_correlation must be in (0, 1]")

    frames_list, video_fps, frame_rate_source = _load_video_frames(video_source, fps)
    n_frames = len(frames_list)

    if not isinstance(initial_points, dict) or not initial_points:
        raise ValueError("initial_points must be a non-empty dictionary mapping keypoint names to (u, v) coordinates")

    sample_frame = frames_list[0]
    h, w = sample_frame.shape[:2]

    validated_initial: dict[str, tuple[float, float]] = {}
    for name, pt in initial_points.items():
        if not isinstance(name, str) or not name:
            raise ValueError("keypoint names must be non-empty strings")
        if not hasattr(pt, "__len__") or len(pt) != 2:
            raise ValueError(f"initial point for '{name}' must have 2 coordinates (u, v)")
        u, v = pt[0], pt[1]
        if (
            not isinstance(u, (int, float, np.number))
            or isinstance(u, bool)
            or not np.isfinite(u)
            or not isinstance(v, (int, float, np.number))
            or isinstance(v, bool)
            or not np.isfinite(v)
        ):
            raise ValueError(f"coordinates for '{name}' must be finite numbers")
        u_f, v_f = float(u), float(v)
        if not (0 <= u_f < w and 0 <= v_f < h):
            raise ValueError(f"initial point for '{name}' ({u_f}, {v_f}) is out of frame bounds ({w}x{h})")
        validated_initial[name] = (u_f, v_f)

    metres_per_pixel = _resolve_scale(
        scale_m_per_pixel, reference_distance_m, reference_points, validated_initial
    )

    gray_frames = [
        cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
        for f in frames_list
    ]

    refined_initial: dict[str, tuple[float, float]] = {}
    templates: dict[str, dict[str, Any]] = {}
    subpix_criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.03)

    r = max(2, template_size // 2)

    for name, (u0, v0) in validated_initial.items():
        u_ref, v_ref = u0, v0
        if subpixel:
            pt_arr = np.array([[[u0, v0]]], dtype=np.float32)
            try:
                pts_refined = cv2.cornerSubPix(gray_frames[0], pt_arr, (5, 5), (-1, -1), subpix_criteria)
                rf_u = float(pts_refined[0, 0, 0])
                rf_v = float(pts_refined[0, 0, 1])
                if np.hypot(rf_u - u0, rf_v - v0) <= 5.0 and 0 <= rf_u < w and 0 <= rf_v < h:
                    u_ref, v_ref = rf_u, rf_v
            except Exception:
                pass
        refined_initial[name] = (u_ref, v_ref)

        cu, cv_ = int(round(u_ref)), int(round(v_ref))
        x0 = max(0, cu - r)
        x1 = min(w, cu + r + 1)
        y0 = max(0, cv_ - r)
        y1 = min(h, cv_ + r + 1)
        patch = gray_frames[0][y0:y1, x0:x1].copy()
        templates[name] = {
            "patch": patch,
            "offset_u": u_ref - x0,
            "offset_v": v_ref - y0,
            "valid": patch.shape[0] >= 3 and patch.shape[1] >= 3,
        }

    raw_coords: dict[str, list[tuple[float, float]]] = {name: [] for name in validated_initial}
    for name in validated_initial:
        raw_coords[name].append(refined_initial[name])

    lk_win = (template_size, template_size) if template_size % 2 == 1 else (21, 21)
    lk_criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01)
    search_radius = max(5, search_window // 2)

    for i in range(1, n_frames):
        prev_gray = gray_frames[i - 1]
        curr_gray = gray_frames[i]

        for name in validated_initial:
            prev_pt = raw_coords[name][-1]
            has_prev = not np.isnan(prev_pt[0])

            last_known: tuple[float, float] | None = None
            for past_pt in reversed(raw_coords[name]):
                if not np.isnan(past_pt[0]):
                    last_known = past_pt
                    break

            curr_pt: tuple[float, float] | None = None

            if tracking_method == "optical_flow" and has_prev:
                p0 = np.array([[[prev_pt[0], prev_pt[1]]]], dtype=np.float32)
                p1, st_fwd, _ = cv2.calcOpticalFlowPyrLK(
                    prev_gray,
                    curr_gray,
                    p0,
                    None,
                    winSize=lk_win,
                    maxLevel=3,
                    criteria=lk_criteria,
                    flags=0,
                    minEigThreshold=1e-4,
                )
                if st_fwd is not None and st_fwd[0, 0] == 1:
                    u1, v1 = float(p1[0, 0, 0]), float(p1[0, 0, 1])
                    if 0 <= u1 < w and 0 <= v1 < h:
                        p0_back, st_bwd, _ = cv2.calcOpticalFlowPyrLK(
                            curr_gray,
                            prev_gray,
                            p1,
                            None,
                            winSize=lk_win,
                            maxLevel=3,
                            criteria=lk_criteria,
                            flags=0,
                            minEigThreshold=1e-4,
                        )
                        if st_bwd is not None and st_bwd[0, 0] == 1:
                            fb_err = float(
                                np.hypot(p0[0, 0, 0] - p0_back[0, 0, 0], p0[0, 0, 1] - p0_back[0, 0, 1])
                            )
                            if fb_err <= fb_threshold:
                                if subpixel:
                                    try:
                                        pts_cand = np.array([[[u1, v1]]], dtype=np.float32)
                                        ref = cv2.cornerSubPix(curr_gray, pts_cand, (3, 3), (-1, -1), subpix_criteria)
                                        ru, rv = float(ref[0, 0, 0]), float(ref[0, 0, 1])
                                        if np.hypot(ru - u1, rv - v1) <= 2.0 and 0 <= ru < w and 0 <= rv < h:
                                            u1, v1 = ru, rv
                                    except Exception:
                                        pass
                                curr_pt = (u1, v1)

            should_try_template = (
                curr_pt is None
                and (tracking_method == "template" or template_fallback)
                and templates[name]["valid"]
                and last_known is not None
            )

            if should_try_template:
                t_info = templates[name]
                patch = t_info["patch"]
                th, tw = patch.shape[:2]
                lu, lv = last_known
                rx0 = max(0, int(round(lu)) - search_radius - r)
                rx1 = min(w, int(round(lu)) + search_radius + r + 1)
                ry0 = max(0, int(round(lv)) - search_radius - r)
                ry1 = min(h, int(round(lv)) + search_radius + r + 1)
                roi = curr_gray[ry0:ry1, rx0:rx1]

                if roi.shape[0] >= th and roi.shape[1] >= tw:
                    res = cv2.matchTemplate(roi, patch, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val >= min_correlation:
                        sub_px, sub_py = _subpixel_peak_fit(res, max_loc)
                        cand_u = rx0 + sub_px + t_info["offset_u"]
                        cand_v = ry0 + sub_py + t_info["offset_v"]
                        if 0 <= cand_u < w and 0 <= cand_v < h:
                            curr_pt = (cand_u, cand_v)

            if curr_pt is not None:
                raw_coords[name].append(curr_pt)
            else:
                raw_coords[name].append((float("nan"), float("nan")))

    frames_idx = np.arange(n_frames)
    t = frames_idx / video_fps
    detected_fractions: dict[str, float] = {}
    clean_coords: dict[str, np.ndarray] = {}

    for name, pts_list in raw_coords.items():
        arr = np.array(pts_list, dtype=np.float64)
        u, v = arr[:, 0], arr[:, 1]
        found = ~np.isnan(u)
        frac = float(found.mean())
        detected_fractions[name] = frac
        if found.sum() < 3:
            raise ValueError(
                f"keypoint '{name}' tracked in only {int(found.sum())} of {n_frames} frames"
            )
        u_interp = _subpixel_interp(frames_idx, frames_idx[found], u[found])
        v_interp = _subpixel_interp(frames_idx, frames_idx[found], v[found])
        uv_clean = np.column_stack([u_interp, v_interp])
        if intrinsics is not None:
            uv_clean = intrinsics.undistort_points(uv_clean)
        clean_coords[name] = uv_clean

    trajectories, omega, foot_path, crank_angle = _compute_trajectories_and_kinematics(
        clean_coords=clean_coords,
        metres_per_pixel=metres_per_pixel,
        t=t,
        n_frames=n_frames,
        forward_is_left=forward_is_left,
    )

    warnings: list[str] = []
    for name, frac in detected_fractions.items():
        if frac < 0.9:
            warnings.append(f"keypoint '{name}' tracked in only {frac * 100:.0f} % of frames; gaps interpolated")
    if video_fps < 25:
        warnings.append(f"video is {video_fps:.0f} fps; temporal resolution is coarse")

    tracking_metadata = {
        "method": "lucas_kanade_optical_flow" if tracking_method == "optical_flow" else "template_matching",
        "initial_points": {k: [float(c) for c in pt] for k, pt in validated_initial.items()},
        "scale_m_per_pixel": metres_per_pixel,
        "forward_is_left": forward_is_left,
        "subpixel": subpixel,
        "fb_threshold": fb_threshold,
        "template_fallback": template_fallback,
        "tracking_method": tracking_method,
        "frame_rate_source": frame_rate_source,
        "first_frame_index": 0,
    }

    return MultiKeypointTrackResult(
        t=t,
        trajectories=trajectories,
        omega=omega,
        foot_path=foot_path,
        crank_angle=crank_angle,
        fps=video_fps,
        frames=n_frames,
        detected_fractions=detected_fractions,
        metres_per_pixel=metres_per_pixel,
        warnings=warnings,
        synthetic=synthetic,
        raw_source=raw_source or (str(video_source) if isinstance(video_source, (str, Path)) else None),
        camera_calibration={
            "camera_matrix": intrinsics.camera_matrix.tolist(),
            "dist_coeffs": intrinsics.dist_coeffs.tolist(),
            "image_size": list(intrinsics.image_size),
            "reprojection_error_px": intrinsics.reprojection_error,
        } if intrinsics is not None else None,
        tracking_metadata=tracking_metadata,
    )


def track_natural_feature(
    video_source: str | Path | Sequence[np.ndarray],
    initial_points: dict[str, tuple[float, float] | Sequence[float] | np.ndarray],
    scale_m_per_pixel: float | None = None,
    *,
    fps: float | None = None,
    forward_is_left: bool = False,
    intrinsics: CameraIntrinsics | None = None,
    subpixel: bool = True,
    fb_threshold: float = 1.0,
    template_fallback: bool = True,
    template_size: int = 21,
    search_window: int = 41,
    min_correlation: float = 0.5,
    tracking_method: str = "optical_flow",
    reference_points: tuple[str, str] | Sequence[str] | None = None,
    reference_distance_m: float | None = None,
    synthetic: bool | None = None,
    raw_source: str | None = None,
) -> MultiKeypointTrackResult:
    """Track natural/markerless features using optical flow with forward-backward consistency and template fallback."""
    return track_point_optical_flow(
        video_source=video_source,
        initial_points=initial_points,
        scale_m_per_pixel=scale_m_per_pixel,
        fps=fps,
        forward_is_left=forward_is_left,
        intrinsics=intrinsics,
        subpixel=subpixel,
        fb_threshold=fb_threshold,
        template_fallback=template_fallback,
        template_size=template_size,
        search_window=search_window,
        min_correlation=min_correlation,
        tracking_method=tracking_method,
        reference_points=reference_points,
        reference_distance_m=reference_distance_m,
        synthetic=synthetic,
        raw_source=raw_source,
    )
