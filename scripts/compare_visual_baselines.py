#!/usr/bin/env python3
"""Viewport visual regression and diff image comparison tool (Q-02).

Acceptance Criteria:
  - Compares viewport/screenshot captures against visual baselines.
  - Calculates pixel-level difference, RMSE, and SSIM.
  - Generates diff heatmap image (diff-{name}.png) and side-by-side comparison
    when difference exceeds threshold.
  - Supports CLI flags: --baseline-dir, --target-dir, --diff-dir, --threshold.

Usage:
  python scripts/compare_visual_baselines.py \
      --baseline-dir docs/assets/screens \
      --target-dir docs/assets/screens \
      --diff-dir test-results/visual-diffs \
      --threshold 0.001
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import scipy.ndimage as ndi
except ImportError:
    ndi = None


@dataclass
class VisualDiffResult:
    name: str
    baseline_path: str
    target_path: str
    width: int
    height: int
    mismatched_pixels: int
    total_pixels: int
    mismatch_ratio: float
    mean_abs_diff: float
    max_abs_diff: float
    rmse_raw: float
    rmse_norm: float
    ssim: float
    exceeds_threshold: bool
    diff_image_path: str | None = None
    sidebyside_image_path: str | None = None
    error: str | None = None


def compute_gaussian_blur(img: np.ndarray, sigma: float = 1.5, kernel_size: int = 11) -> np.ndarray:
    """Apply Gaussian blur with cv2 or scipy fallback."""
    if cv2 is not None:
        return cv2.GaussianBlur(img, (kernel_size, kernel_size), sigma)
    elif ndi is not None:
        return ndi.gaussian_filter(img, sigma=sigma, mode="reflect")
    else:
        # Simple uniform box fallback if neither cv2 nor scipy is available
        pad = kernel_size // 2
        padded = np.pad(img, pad, mode="reflect")
        out = np.zeros_like(img)
        for i in range(kernel_size):
            for j in range(kernel_size):
                out += padded[i : i + img.shape[0], j : j + img.shape[1]]
        return out / (kernel_size * kernel_size)


def compute_ssim(
    arr1: np.ndarray,
    arr2: np.ndarray,
    k1: float = 0.01,
    k2: float = 0.03,
    dynamic_range: float = 255.0,
) -> float:
    """Compute mean Structural Similarity Index (SSIM) on luminance."""
    # Convert RGB to luminance
    if arr1.ndim == 3 and arr1.shape[2] >= 3:
        y1 = 0.299 * arr1[:, :, 0] + 0.587 * arr1[:, :, 1] + 0.114 * arr1[:, :, 2]
        y2 = 0.299 * arr2[:, :, 0] + 0.587 * arr2[:, :, 1] + 0.114 * arr2[:, :, 2]
    else:
        y1 = arr1.astype(np.float32)
        y2 = arr2.astype(np.float32)

    c1 = (k1 * dynamic_range) ** 2
    c2 = (k2 * dynamic_range) ** 2

    mu1 = compute_gaussian_blur(y1, sigma=1.5, kernel_size=11)
    mu2 = compute_gaussian_blur(y2, sigma=1.5, kernel_size=11)

    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = compute_gaussian_blur(y1 ** 2, sigma=1.5, kernel_size=11) - mu1_sq
    sigma2_sq = compute_gaussian_blur(y2 ** 2, sigma=1.5, kernel_size=11) - mu2_sq
    sigma12 = compute_gaussian_blur(y1 * y2, sigma=1.5, kernel_size=11) - mu1_mu2

    num = (2 * mu1_mu2 + c1) * (2 * sigma12 + c2)
    den = (mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2)
    ssim_map = num / den

    # Clip to valid SSIM range [-1, 1]
    return float(np.clip(np.mean(ssim_map), -1.0, 1.0))


def create_diff_heatmap(
    arr1: np.ndarray,
    arr2: np.ndarray,
    channel_threshold: float = 0.0,
) -> Image.Image:
    """Generate a heatmap highlighting differing pixels over a dimmed baseline background."""
    diff = np.abs(arr1.astype(np.float32) - arr2.astype(np.float32))
    diff_max = np.max(diff, axis=-1)  # (H, W)

    # Dimmed grayscale base from baseline (arr1)
    if arr1.ndim == 3 and arr1.shape[2] >= 3:
        gray1 = 0.299 * arr1[:, :, 0] + 0.587 * arr1[:, :, 1] + 0.114 * arr1[:, :, 2]
    else:
        gray1 = arr1.astype(np.float32)

    base_dimmed = (gray1 * 0.35).astype(np.uint8)
    base_rgb = np.stack([base_dimmed, base_dimmed, base_dimmed], axis=-1)

    mask = diff_max > channel_threshold

    if np.any(mask):
        # Normalize diff to [0, 1] for differing pixels with non-linear boost
        diff_norm = np.clip(diff_max / 255.0 * 2.5, 0.0, 1.0)
        # Gradient: Bright yellow (255, 255, 0) -> Red (255, 30, 30) -> Magenta (255, 0, 255)
        r = np.full_like(diff_norm, 255, dtype=np.uint8)
        g = np.clip(255 * (1.0 - diff_norm), 0, 255).astype(np.uint8)
        b = np.clip(220 * diff_norm, 0, 255).astype(np.uint8)
        highlight = np.stack([r, g, b], axis=-1)

        result = base_rgb.copy()
        result[mask] = highlight[mask]
    else:
        result = base_rgb

    return Image.fromarray(result)


def create_side_by_side_composite(
    im_baseline: Image.Image,
    im_target: Image.Image,
    im_diff: Image.Image,
    title: str,
    subtitle: str,
) -> Image.Image:
    """Compose [ Baseline | Target | Diff Heatmap ] with title headers."""
    w, h = im_baseline.size
    banner_height = 64
    label_height = 28
    header_height = banner_height + label_height
    padding = 12

    total_w = w * 3 + padding * 4
    total_h = h + header_height + padding * 2

    canvas = Image.new("RGB", (total_w, total_h), color=(18, 20, 24))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    # Draw header banner
    draw.rectangle([0, 0, total_w, banner_height], fill=(28, 32, 40))
    draw.text((padding, 12), title, fill=(240, 245, 255), font=font)
    draw.text((padding, 36), subtitle, fill=(180, 195, 215), font=font)

    # Column labels
    col1_x = padding
    col2_x = padding * 2 + w
    col3_x = padding * 3 + w * 2
    y_labels = banner_height + 6
    draw.text((col1_x, y_labels), "BASELINE", fill=(160, 180, 200), font=font)
    draw.text((col2_x, y_labels), "TARGET", fill=(160, 180, 200), font=font)
    draw.text((col3_x, y_labels), "DIFF HEATMAP", fill=(255, 120, 120), font=font)

    # Paste images
    y_img = header_height + padding
    canvas.paste(im_baseline, (col1_x, y_img))
    canvas.paste(im_target, (col2_x, y_img))
    canvas.paste(im_diff, (col3_x, y_img))

    return canvas


def compare_images(
    baseline_path: Path,
    target_path: Path,
    diff_dir: Path | None = None,
    threshold: float = 0.0,
    channel_threshold: float = 0.0,
    generate_sidebyside: bool = True,
    name: str | None = None,
) -> VisualDiffResult:
    """Compare a single baseline image against a target image."""
    image_name = name or baseline_path.name

    if not baseline_path.exists():
        return VisualDiffResult(
            name=image_name,
            baseline_path=str(baseline_path),
            target_path=str(target_path),
            width=0,
            height=0,
            mismatched_pixels=0,
            total_pixels=0,
            mismatch_ratio=1.0,
            mean_abs_diff=255.0,
            max_abs_diff=255.0,
            rmse_raw=255.0,
            rmse_norm=1.0,
            ssim=0.0,
            exceeds_threshold=True,
            error=f"Baseline image not found: {baseline_path}",
        )

    if not target_path.exists():
        return VisualDiffResult(
            name=image_name,
            baseline_path=str(baseline_path),
            target_path=str(target_path),
            width=0,
            height=0,
            mismatched_pixels=0,
            total_pixels=0,
            mismatch_ratio=1.0,
            mean_abs_diff=255.0,
            max_abs_diff=255.0,
            rmse_raw=255.0,
            rmse_norm=1.0,
            ssim=0.0,
            exceeds_threshold=True,
            error=f"Target image not found: {target_path}",
        )

    im_base = Image.open(baseline_path).convert("RGB")
    im_target = Image.open(target_path).convert("RGB")

    w1, h1 = im_base.size
    w2, h2 = im_target.size

    if (w1, h1) != (w2, h2):
        return VisualDiffResult(
            name=image_name,
            baseline_path=str(baseline_path),
            target_path=str(target_path),
            width=w1,
            height=h1,
            mismatched_pixels=w1 * h1,
            total_pixels=w1 * h1,
            mismatch_ratio=1.0,
            mean_abs_diff=255.0,
            max_abs_diff=255.0,
            rmse_raw=255.0,
            rmse_norm=1.0,
            ssim=0.0,
            exceeds_threshold=True,
            error=f"Dimension mismatch: baseline={im_base.size} vs target={im_target.size}",
        )

    arr1 = np.asarray(im_base, dtype=np.float32)
    arr2 = np.asarray(im_target, dtype=np.float32)

    diff_arr = np.abs(arr1 - arr2)
    diff_max_per_pixel = np.max(diff_arr, axis=-1)

    total_pixels = w1 * h1
    mismatched_pixels = int(np.sum(diff_max_per_pixel > channel_threshold))
    mismatch_ratio = float(mismatched_pixels / total_pixels) if total_pixels > 0 else 0.0

    mean_abs_diff = float(np.mean(diff_arr))
    max_abs_diff = float(np.max(diff_arr))

    rmse_raw = float(np.sqrt(np.mean((arr1 - arr2) ** 2)))
    rmse_norm = float(rmse_raw / 255.0)

    ssim_val = compute_ssim(arr1, arr2)

    # Threshold evaluation: exceeds if mismatch_ratio > threshold or rmse_norm > threshold
    exceeds_threshold = (mismatch_ratio > threshold) or (rmse_norm > threshold)

    diff_img_path_str: str | None = None
    sidebyside_path_str: str | None = None

    if diff_dir is not None and (exceeds_threshold or mismatched_pixels > 0):
        diff_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = Path(image_name).stem.replace("/", "_").replace("\\", "_")

        # 1. Diff heatmap image: diff-{name}.png
        heatmap_im = create_diff_heatmap(arr1, arr2, channel_threshold=channel_threshold)
        diff_out_file = diff_dir / f"diff-{safe_stem}.png"
        heatmap_im.save(diff_out_file)
        diff_img_path_str = str(diff_out_file)

        # 2. Side-by-side composite
        if generate_sidebyside:
            title = f"Visual Regression Diff: {image_name}"
            subtitle = (
                f"Mismatch: {mismatch_ratio * 100:.3f}% ({mismatched_pixels}/{total_pixels} px) | "
                f"RMSE: {rmse_norm:.5f} ({rmse_raw:.2f}/255) | SSIM: {ssim_val:.5f} | "
                f"Threshold: {threshold}"
            )
            sidebyside_im = create_side_by_side_composite(
                im_base, im_target, heatmap_im, title, subtitle
            )
            sidebyside_out_file = diff_dir / f"diff-sidebyside-{safe_stem}.png"
            sidebyside_im.save(sidebyside_out_file)
            sidebyside_path_str = str(sidebyside_out_file)

    return VisualDiffResult(
        name=image_name,
        baseline_path=str(baseline_path),
        target_path=str(target_path),
        width=w1,
        height=h1,
        mismatched_pixels=mismatched_pixels,
        total_pixels=total_pixels,
        mismatch_ratio=mismatch_ratio,
        mean_abs_diff=mean_abs_diff,
        max_abs_diff=max_abs_diff,
        rmse_raw=rmse_raw,
        rmse_norm=rmse_norm,
        ssim=ssim_val,
        exceeds_threshold=exceeds_threshold,
        diff_image_path=diff_img_path_str,
        sidebyside_image_path=sidebyside_path_str,
        error=None,
    )


def compare_directories(
    baseline_dir: Path,
    target_dir: Path,
    diff_dir: Path,
    threshold: float = 0.0,
    channel_threshold: float = 0.0,
    generate_sidebyside: bool = True,
    patterns: tuple[str, ...] = ("*.png", "*.jpg", "*.jpeg"),
    verbose: bool = True,
) -> tuple[int, list[VisualDiffResult]]:
    """Compare all images matching patterns across two directories."""
    if not baseline_dir.exists():
        if verbose:
            print(f"Error: Baseline directory not found: {baseline_dir}")
        return 2, []

    if not target_dir.exists():
        if verbose:
            print(f"Error: Target directory not found: {target_dir}")
        return 2, []

    # Collect baseline files
    baseline_files: list[Path] = []
    for pat in patterns:
        baseline_files.extend(baseline_dir.rglob(pat))
    baseline_files = sorted(set(baseline_files))

    if not baseline_files:
        if verbose:
            print(f"Warning: No images found in baseline directory: {baseline_dir}")
        return 0, []

    results: list[VisualDiffResult] = []
    any_failed = False

    for b_path in baseline_files:
        rel_path = b_path.relative_to(baseline_dir)
        t_path = target_dir / rel_path

        res = compare_images(
            baseline_path=b_path,
            target_path=t_path,
            diff_dir=diff_dir,
            threshold=threshold,
            channel_threshold=channel_threshold,
            generate_sidebyside=generate_sidebyside,
            name=str(rel_path),
        )
        results.append(res)

        if res.error or res.exceeds_threshold:
            any_failed = True

        if verbose:
            status = "FAILED" if (res.error or res.exceeds_threshold) else "PASSED"
            if res.error:
                print(f"[{status}] {rel_path}: {res.error}")
            else:
                pct = res.mismatch_ratio * 100.0
                print(
                    f"[{status}] {rel_path}: mismatch={pct:.2f}% ({res.mismatched_pixels} px), "
                    f"rmse={res.rmse_norm:.4f}, ssim={res.ssim:.4f}"
                )
                if res.diff_image_path:
                    print(f"         Diff heatmap saved: {res.diff_image_path}")
                if res.sidebyside_image_path:
                    print(f"         Side-by-side saved: {res.sidebyside_image_path}")

    exit_code = 1 if any_failed else 0
    return exit_code, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Viewport visual regression and diff image comparison tool (Q-02)."
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=Path("docs/assets/screens"),
        help="Path to baseline images directory (default: docs/assets/screens).",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path("docs/assets/screens"),
        help="Path to target/current screenshots directory (default: docs/assets/screens).",
    )
    parser.add_argument(
        "--diff-dir",
        type=Path,
        default=Path("test-results/visual-diffs"),
        help="Path to directory where diff images will be saved (default: test-results/visual-diffs).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Mismatch tolerance threshold (0.0 to 1.0; 0.0 requires exact match, default: 0.0).",
    )
    parser.add_argument(
        "--channel-threshold",
        type=float,
        default=0.0,
        help="Per-channel color difference threshold in [0, 255] before flagging a pixel (default: 0.0).",
    )
    parser.add_argument(
        "--no-side-by-side",
        action="store_true",
        help="Disable generation of 3-column side-by-side comparison images.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON summary.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress console progress output.",
    )

    args = parser.parse_args(argv)

    exit_code, results = compare_directories(
        baseline_dir=args.baseline_dir,
        target_dir=args.target_dir,
        diff_dir=args.diff_dir,
        threshold=args.threshold,
        channel_threshold=args.channel_threshold,
        generate_sidebyside=not args.no_side_by_side,
        verbose=not args.quiet and not args.json,
    )

    if args.json:
        report = {
            "exit_code": exit_code,
            "threshold": args.threshold,
            "channel_threshold": args.channel_threshold,
            "images_compared": len(results),
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(report, indent=2))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
