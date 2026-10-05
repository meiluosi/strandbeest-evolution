import cv2
import numpy as np
import pytest

from strandbeest_rig.serial_log import log_lines
from strandbeest_rig.video_track import track_marker


def make_video(path, speed_m_s=0.05, marker_mm=20.0, marker_px=100, fps=30, seconds=3.0, marker_id=7, with_marker=True):
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(d, marker_id, marker_px)
    marker = cv2.copyMakeBorder(marker, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)  # quiet zone
    mpp = marker_mm / 1000 / marker_px
    px_per_s = speed_m_s / mpp
    w, h = 1400, 400
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for i in range(int(seconds * fps)):
        frame = np.full((h, w), 255, np.uint8)
        x0 = int(100 + px_per_s * i / fps)
        if with_marker:
            frame[100 : 100 + marker.shape[0], x0 : x0 + marker.shape[1]] = marker
        out.write(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
    out.release()
    return mpp


def test_tracker_recovers_speed_from_a_synthetic_video(tmp_path):
    p = tmp_path / "v.avi"
    make_video(p, speed_m_s=0.05)
    r = track_marker(str(p), 7, 20.0)
    slope = np.polyfit(r.t, r.x, 1)[0]
    assert slope == pytest.approx(0.05, rel=0.03)
    assert r.detected_fraction > 0.95 and r.x[0] == 0.0


def test_forward_left_flips_the_sign(tmp_path):
    p = tmp_path / "v.avi"
    make_video(p)
    assert track_marker(str(p), 7, 20.0, forward_is_left=True).x[-1] < 0


def test_missing_marker_is_a_clear_error(tmp_path):
    p = tmp_path / "v.avi"
    make_video(p, with_marker=False)
    with pytest.raises(ValueError, match="found in only"):
        track_marker(str(p), 7, 20.0)


def test_log_lines_stops_at_the_duration_and_skips_blank_lines(tmp_path):
    clock = iter(range(1000))
    n = log_lines(iter(["a\r\n", "", "b\n", "c\n", "d\n", "e\n"]), tmp_path / "o.csv", duration_s=3, now=lambda: next(clock))
    assert (tmp_path / "o.csv").read_text().splitlines() == ["a", "b", "c", "d"][: n]
    assert n < 5
