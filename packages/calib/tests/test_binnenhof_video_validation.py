"""Tests for H4-01 / V-05 / H3-03 Binnenhof physical video tracking and digital twin validation."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from strandbeest_calib.binnenhof_video import (
    ANIMARIS_HEIGHT_M,
    CALIBRATED_MPP,
    SCALE_UNCERTAINTY_MPP,
    THEO_JANSEN_HEIGHT_M,
    build_measurement_asset,
    run_digital_twin_forward_comparison,
    run_video_tracking,
)
from strandbeest_calib.community import validate_submission
from strandbeest_common.schemas import validate


def test_binnenhof_scale_calibration_constants():
    """Verify physical scale calibration ratios from human and machine references."""
    assert THEO_JANSEN_HEIGHT_M == pytest.approx(1.85, abs=0.01)
    assert ANIMARIS_HEIGHT_M == pytest.approx(2.36, abs=0.02)
    assert CALIBRATED_MPP == pytest.approx(0.003895, rel=1e-3)
    # Relative scale uncertainty is ~5.4%
    rel_unc = SCALE_UNCERTAINTY_MPP / CALIBRATED_MPP
    assert 0.04 <= rel_unc <= 0.07


def test_synthetic_video_tracking_pipeline():
    """Test video tracking routine on synthetic frames moving at the empirical speed."""
    fps = 30.0
    n_frames = 60
    scale_mpp = CALIBRATED_MPP
    v_walk = 0.126  # m/s
    dx_per_frame_m = v_walk / fps
    dx_per_frame_px = dx_per_frame_m / scale_mpp

    frames = []
    x0, y0 = 484.0, 401.0
    for i in range(n_frames):
        img = np.full((500, 600, 3), 128, dtype=np.uint8)
        # Draw high-contrast feature moving horizontally
        cx = int(round(x0 + i * dx_per_frame_px))
        cy = int(y0)
        img[cy - 8 : cy + 8, cx - 8 : cx + 8] = 240
        img[cy - 2 : cy + 2, cx - 2 : cx + 2] = 20
        frames.append(img)

    track_data = run_video_tracking(frames, fps, scale_mpp=scale_mpp)
    assert track_data["dx_m"] == pytest.approx(v_walk * (n_frames - 1) / fps, abs=0.02)
    assert track_data["v_mean_m_s"] == pytest.approx(v_walk, abs=0.01)
    assert track_data["f_crank_hz"] == pytest.approx(0.045, rel=1e-2)
    assert track_data["stride_per_rev_m"] > 2.0


def test_measurement_asset_creation_and_schema_validation():
    """Test generating a valid Schema v2 Measurement asset with complete provenance."""
    track_data = {
        "t": [0.0, 1.0, 2.0, 3.0],
        "x": [0.0, 0.126, 0.252, 0.378],
        "y": [0.0, 0.01, -0.01, 0.0],
        "psi": [0.0, 0.2827, 0.5654, 0.8481],
        "dx_m": 0.378,
        "dt_s": 3.0,
        "v_mean_m_s": 0.126,
        "f_crank_hz": 0.045,
        "crank_period_s": 22.22,
        "omega_mean_rad_s": 0.2827,
        "stride_per_rev_m": 2.80,
        "warnings": [],
    }
    doc = build_measurement_asset(track_data)
    # Strict schema validation
    validate("measurement", doc)
    assert doc["schema_version"] == 2
    assert doc["synthetic"] is False
    assert doc["provenance"]["calibration"]["licence"] == "CC BY 3.0"
    assert doc["provenance"]["calibration"]["units"]["x"] == "m"
    assert doc["provenance"]["calibration"]["units"]["psi"] == "rad"
    assert doc["provenance"]["calibration"]["uncertainty"]["x"] == 0.08

    # Validate with community submission checker
    rep = validate_submission(doc)
    assert rep.ok is True
    assert len(rep.errors) == 0
    # Must report torque as missing (truthful reporting, no faking)
    assert any("torque" in m for m in rep.missing)


def test_digital_twin_forward_comparison_bounds():
    """Test digital twin forward simulation comparison and uncertainty bounding."""
    track_data = {
        "omega_mean_rad_s": 0.2827,
        "stride_per_rev_m": 2.8008,
    }
    comp = run_digital_twin_forward_comparison(track_data)

    assert comp["stride_physical_m"] == pytest.approx(2.8008, abs=1e-3)
    assert comp["stride_kinematic_ideal_m"] == pytest.approx(2.8747, abs=0.05)
    # MuJoCo stride should match within 10%
    assert comp["rel_diff_mujoco_pct"] < 10.0
    # Kinematic ideal difference should match within 5%
    assert comp["rel_diff_kinematic_pct"] < 5.0
    # Must be within 95% uncertainty envelope (+/- 1.96 sigma)
    assert comp["within_uncertainty_envelope"] is True
    # Literature comparison metadata must cite Nansai et al. 2015
    assert "Nansai" in comp["literature_comparison"]["source"]
    assert comp["literature_comparison"]["prototype_error_pct"] == 16.07
