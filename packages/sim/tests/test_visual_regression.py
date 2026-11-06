"""Q-02: Viewport visual regression and diff image comparison tests.

Acceptance criteria:
  - Compares viewport screenshots against visual baselines.
  - Calculates pixel-level difference, RMSE, and SSIM.
  - Generates diff heatmap image (diff-{name}.png) and side-by-side comparison
    when difference exceeds threshold.
  - Test identical images yield zero difference.
  - Test synthetic pixel modification generates diff image and non-zero mismatch score.
  - Test CLI execution and return codes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compare_visual_baselines import (  # noqa: E402
    compare_directories,
    compare_images,
    compute_ssim,
    create_diff_heatmap,
    create_side_by_side_composite,
)


@pytest.fixture
def temp_visual_dir(tmp_path: Path):
    """Set up temporary directories for visual testing."""
    baseline_dir = tmp_path / "baseline"
    target_dir = tmp_path / "target"
    diff_dir = tmp_path / "diffs"

    baseline_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    diff_dir.mkdir(parents=True, exist_ok=True)

    return baseline_dir, target_dir, diff_dir


def test_identical_images_yield_zero_difference(temp_visual_dir):
    """Verify that comparing identical images produces zero difference and SSIM=1.0."""
    baseline_dir, target_dir, diff_dir = temp_visual_dir

    # Create synthetic test image (e.g. 200x150 with geometric shapes)
    w, h = 200, 150
    im = Image.new("RGB", (w, h), color=(30, 35, 45))
    draw = ImageDraw.Draw(im)
    draw.rectangle([20, 20, 80, 80], fill=(70, 130, 180), outline=(200, 200, 200))
    draw.ellipse([100, 40, 160, 100], fill=(220, 100, 80))

    base_path = baseline_dir / "viewport-sample.png"
    target_path = target_dir / "viewport-sample.png"

    im.save(base_path)
    im.save(target_path)  # Exact copy

    res = compare_images(
        baseline_path=base_path,
        target_path=target_path,
        diff_dir=diff_dir,
        threshold=0.0,
    )

    assert not res.error
    assert res.mismatched_pixels == 0
    assert res.mismatch_ratio == 0.0
    assert res.mean_abs_diff == 0.0
    assert res.max_abs_diff == 0.0
    assert res.rmse_raw == 0.0
    assert res.rmse_norm == 0.0
    assert res.ssim == pytest.approx(1.0, abs=1e-5)
    assert not res.exceeds_threshold
    assert res.diff_image_path is None


def test_synthetic_pixel_modification_generates_diff_and_scores(temp_visual_dir):
    """Verify that a synthetic modification generates diff images and non-zero mismatch scores."""
    baseline_dir, target_dir, diff_dir = temp_visual_dir

    w, h = 200, 150
    im_base = Image.new("RGB", (w, h), color=(30, 35, 45))
    draw_base = ImageDraw.Draw(im_base)
    draw_base.rectangle([20, 20, 80, 80], fill=(70, 130, 180))

    im_target = im_base.copy()
    draw_target = ImageDraw.Draw(im_target)
    # Modify a 30x30 patch (900 pixels) with a bright red square (geometry / style regression)
    draw_target.rectangle([110, 50, 140, 80], fill=(255, 30, 30))

    base_path = baseline_dir / "linkage-view.png"
    target_path = target_dir / "linkage-view.png"

    im_base.save(base_path)
    im_target.save(target_path)

    res = compare_images(
        baseline_path=base_path,
        target_path=target_path,
        diff_dir=diff_dir,
        threshold=0.001,  # Strict threshold
        name="linkage-view.png",
    )

    assert not res.error
    assert res.mismatched_pixels > 0
    assert res.mismatch_ratio > 0.0
    assert res.rmse_raw > 0.0
    assert res.rmse_norm > 0.0
    assert res.ssim < 1.0
    assert res.exceeds_threshold is True

    # Assert diff heatmap image exists
    assert res.diff_image_path is not None
    diff_file = Path(res.diff_image_path)
    assert diff_file.exists()
    assert diff_file.name == "diff-linkage-view.png"

    # Assert side-by-side comparison image exists
    assert res.sidebyside_image_path is not None
    sbs_file = Path(res.sidebyside_image_path)
    assert sbs_file.exists()
    assert sbs_file.name == "diff-sidebyside-linkage-view.png"

    # Verify diff image contains non-black highlight pixels in modified area
    diff_im = Image.open(diff_file)
    diff_arr = np.asarray(diff_im)
    assert diff_arr.shape == (h, w, 3)
    # Check that pixels in modified area (y: 50..80, x: 110..140) are highlighted with high red channel
    patch_red = diff_arr[55:75, 115:135, 0]
    assert np.all(patch_red >= 200)


def test_dimension_mismatch_flags_error(temp_visual_dir):
    """Verify that dimension mismatch between baseline and target is flagged as an error."""
    baseline_dir, target_dir, diff_dir = temp_visual_dir

    im_base = Image.new("RGB", (100, 100), color=(50, 50, 50))
    im_target = Image.new("RGB", (120, 100), color=(50, 50, 50))

    base_path = baseline_dir / "resized.png"
    target_path = target_dir / "resized.png"
    im_base.save(base_path)
    im_target.save(target_path)

    res = compare_images(
        baseline_path=base_path,
        target_path=target_path,
        diff_dir=diff_dir,
    )

    assert res.error is not None
    assert "Dimension mismatch" in res.error
    assert res.exceeds_threshold is True


def test_cli_execution_identical_returns_zero(temp_visual_dir):
    """Test CLI returns exit code 0 when all images match."""
    baseline_dir, target_dir, diff_dir = temp_visual_dir

    im = Image.new("RGB", (50, 50), color=(100, 120, 140))
    im.save(baseline_dir / "test1.png")
    im.save(target_dir / "test1.png")

    script_path = SCRIPTS_DIR / "compare_visual_baselines.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--baseline-dir",
            str(baseline_dir),
            "--target-dir",
            str(target_dir),
            "--diff-dir",
            str(diff_dir),
            "--threshold",
            "0.0",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    assert "[PASSED] test1.png" in proc.stdout


def test_cli_execution_different_exceeds_threshold_returns_one(temp_visual_dir):
    """Test CLI returns exit code 1 when differences exceed threshold."""
    baseline_dir, target_dir, diff_dir = temp_visual_dir

    im1 = Image.new("RGB", (50, 50), color=(100, 120, 140))
    im2 = Image.new("RGB", (50, 50), color=(200, 120, 140))
    im1.save(baseline_dir / "test2.png")
    im2.save(target_dir / "test2.png")

    script_path = SCRIPTS_DIR / "compare_visual_baselines.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--baseline-dir",
            str(baseline_dir),
            "--target-dir",
            str(target_dir),
            "--diff-dir",
            str(diff_dir),
            "--threshold",
            "0.001",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    assert "[FAILED] test2.png" in proc.stdout
    assert "Diff heatmap saved" in proc.stdout
    assert (diff_dir / "diff-test2.png").exists()
    assert (diff_dir / "diff-sidebyside-test2.png").exists()


def test_cli_json_output_format(temp_visual_dir):
    """Test CLI --json output format and structure."""
    baseline_dir, target_dir, diff_dir = temp_visual_dir

    im = Image.new("RGB", (60, 60), color=(50, 60, 70))
    im.save(baseline_dir / "json_test.png")
    im.save(target_dir / "json_test.png")

    script_path = SCRIPTS_DIR / "compare_visual_baselines.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--baseline-dir",
            str(baseline_dir),
            "--target-dir",
            str(target_dir),
            "--diff-dir",
            str(diff_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["exit_code"] == 0
    assert data["images_compared"] == 1
    item = data["results"][0]
    assert item["name"] == "json_test.png"
    assert item["mismatched_pixels"] == 0
    assert item["ssim"] == 1.0
    assert item["rmse_norm"] == 0.0


def test_real_doc_screenshots_self_comparison():
    """Verify that existing documentation screenshots in docs/assets/screens pass self-check."""
    screens_dir = ROOT / "docs" / "assets" / "screens"
    if not screens_dir.exists():
        pytest.skip("docs/assets/screens directory not found")

    exit_code, results = compare_directories(
        baseline_dir=screens_dir,
        target_dir=screens_dir,
        diff_dir=ROOT / "test-results" / "temp-diffs",
        threshold=0.0,
        verbose=False,
    )

    assert exit_code == 0
    assert len(results) >= 8
    for r in results:
        assert not r.error
        assert r.mismatched_pixels == 0
        assert r.mismatch_ratio == 0.0
        assert r.ssim == pytest.approx(1.0, abs=1e-4)
