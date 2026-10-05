"""Track an ArUco marker in a side-view video to get the body's forward position x(t) in metres.

Assumptions (state them in your lab notebook): the camera looks perpendicular to the direction of travel, the marker is flat
on the body facing the camera and sits roughly in the plane of motion, and the camera does not move. Perspective error grows
with the angle; use a long lens or a distant camera.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class TrackResult:
    t: np.ndarray  # seconds from the first frame
    x: np.ndarray  # metres, forward positive, zero at the first detection
    fps: float
    frames: int
    detected_fraction: float
    metres_per_pixel: float
    warnings: list[str] = field(default_factory=list)


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
