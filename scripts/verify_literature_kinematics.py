#!/usr/bin/env python3
"""Inspect the legacy Pop 2014 comparison; its source chain is currently unverified.

Computes scale- and translation-invariant shape distance (as defined in EXPERIMENTS section 1 and packages/core metrics.ts)
using the retained, unverified alignment and uncertainty assumptions.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalise_bbox(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Exact port of packages/core/src/metrics.ts: normalise (bounding box center, width scaled to 1.0)."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = max(xs) - min(xs)
    if w <= 0:
        w = 1.0
    cx = (max(xs) + min(xs)) / 2.0
    cy = (max(ys) + min(ys)) / 2.0
    return [((p[0] - cx) / w, (p[1] - cy) / w) for p in pts]


def mean_nearest(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    tot = 0.0
    for p in a:
        best_sq = min((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for q in b)
        tot += math.sqrt(best_sq)
    return tot / len(a)


def path_distance(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """Symmetric mean nearest-point distance in units of normalized width (packages/core metrics.ts)."""
    na = normalise_bbox(a)
    nb = normalise_bbox(b)
    return (mean_nearest(na, nb) + mean_nearest(nb, na)) / 2.0


def solve_analytical_foot_path(samples: int = 180) -> list[tuple[float, float]]:
    from strandbeest_common import load_spec
    from strandbeest_common.gait import foot_path

    jansen_contract = json.loads((ROOT / "contracts" / "kinematics" / "jansen.json").read_text())
    spec = load_spec(jansen_contract["spec"])
    pts = foot_path(spec, samples)
    if pts is None:
        raise RuntimeError("failed to solve analytical Jansen linkage")
    return pts


def render_ascii_plot(
    ana_pts: list[tuple[float, float]],
    lit_pts: list[tuple[float, float]],
    title: str = "Trajectory Comparison",
    cols: int = 60,
    rows: int = 16,
) -> str:
    all_pts = lit_pts + ana_pts
    min_x, max_x = min(p[0] for p in all_pts), max(p[0] for p in all_pts)
    min_y, max_y = min(p[1] for p in all_pts), max(p[1] for p in all_pts)

    grid = [[" " for _ in range(cols)] for _ in range(rows)]

    def to_grid(p: tuple[float, float]) -> tuple[int, int]:
        c = int((p[0] - min_x) / (max_x - min_x) * (cols - 1)) if max_x > min_x else 0
        r = int((max_y - p[1]) / (max_y - min_y) * (rows - 1)) if max_y > min_y else 0
        return min(max(0, c), cols - 1), min(max(0, r), rows - 1)

    for p in ana_pts:
        c, r = to_grid(p)
        grid[r][c] = "·"

    for p in lit_pts:
        c, r = to_grid(p)
        grid[r][c] = "*" if grid[r][c] == " " else "o"

    lines = [f"{title} (· = Analytical 180pts, * = Legacy (unverified), o = Overlap):"]
    lines.append("+" + "-" * cols + "+")
    for r in range(rows):
        y_val = max_y - r / (rows - 1) * (max_y - min_y)
        lines.append(f"|{''.join(grid[r])}| {y_val:6.1f} mm")
    lines.append("+" + "-" * cols + "+")
    lines.append(f" {min_x:6.1f} mm" + " " * max(1, cols - 18) + f"{max_x:6.1f} mm")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unverified-preview", action="store_true",
                        help="Inspect retained historical numbers without granting an evidence level.")
    args = parser.parse_args(argv)
    lit_path = ROOT / "experiments" / "literature-jansen-amm2014.json"
    lit_data = json.loads(lit_path.read_text())
    # A DOI or close numerical agreement cannot authenticate digitized points.
    # Re-enabling validation requires a reviewed source/extraction workflow,
    # not simply changing a metadata flag in the retained historical file.
    if not args.unverified_preview:
        print("V-01 NOT VERIFIED: the historical dataset lacks a reproducible source/extraction chain.")
        print("No E2 upgrade is granted. Use --unverified-preview only to inspect the legacy comparison.")
        return 2
    print("UNVERIFIED PREVIEW: these numbers are not accepted as published experimental data.")
    lit_pts = [tuple(p) for p in lit_data["points_24"]]

    ana_pts = solve_analytical_foot_path(180)
    raw_dist = path_distance(lit_pts, ana_pts)

    # Calculate bounding metrics
    xs_lit, ys_lit = [p[0] for p in lit_pts], [p[1] for p in lit_pts]
    width_lit = max(xs_lit) - min(xs_lit)
    lift_lit = max(ys_lit) - min(ys_lit)

    xs_ana, ys_ana = [p[0] for p in ana_pts], [p[1] for p in ana_pts]
    width_ana = max(xs_ana) - min(xs_ana)
    lift_ana = max(ys_ana) - min(ys_ana)

    uncertainty_mm = lit_data.get("digitization_uncertainty_mm", 0.8)
    sigma = uncertainty_mm / width_ana

    # Historical alignment constants; their physical origin has not been verified.
    rad = math.radians(-1.0)
    c, s = math.cos(rad), math.sin(rad)
    aligned_lit = [(p[0] * c - p[1] * s - 4.5, p[0] * s + p[1] * c - 0.5) for p in lit_pts]
    aligned_dist = path_distance(aligned_lit, ana_pts)

    print("=== Legacy numerical comparison (source unverified) ===")
    print(f"Source: {lit_data['source']}")
    print(f"Analytical path points: {len(ana_pts)}, Literature points: {len(lit_pts)}")
    print(f"Analytical dimensions: width = {width_ana:.3f} mm, lift = {lift_ana:.3f} mm, aspect ratio = {lift_ana/width_ana:.4f}")
    print(f"Literature dimensions: width = {width_lit:.3f} mm, lift = {lift_lit:.3f} mm, aspect ratio = {lift_lit/width_lit:.4f}")
    print(f"Unverified legacy metrics: stroke {lit_data['reported_metrics']['stroke_length_mm']} mm, lift {lit_data['reported_metrics']['lift_mm']} mm, duty {lit_data['reported_metrics']['duty_factor']}")
    print(f"Unverified legacy uncertainty: ±{uncertainty_mm:.2f} mm (±{sigma:.4f} of path width)")
    print(f"Raw shape distance (EXPERIMENTS §1 definition): {raw_dist:.5f}")
    print(f"Aligned shape distance (-1.0 deg, dx=-4.5 mm, dy=-0.5 mm): {aligned_dist:.5f}")
    # Mean absolute physical discrepancy in mm (after rigid alignment to compensate for image rotation)
    dists_mm = [
        min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in ana_pts) for p in aligned_lit
    ]
    mean_error_mm = sum(dists_mm) / len(dists_mm)
    max_error_stance_mm = max(
        min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in ana_pts)
        for p in lit_pts[:8]
    )

    print(f"Mean physical error after alignment: {mean_error_mm:.3f} mm ({mean_error_mm/width_ana*100:.2f}% of width)")
    print(f"Max discrepancy on the historical first-eight-point subset: {max_error_stance_mm:.3f} mm")
    print()
    print(render_ascii_plot(ana_pts, lit_pts, title="Raw Foot Trajectory Comparison"))
    print()
    print(render_ascii_plot(ana_pts, aligned_lit, title="Aligned Foot Trajectory Comparison"))
    print()

    print("Preview complete. Numerical agreement does not verify provenance; no evidence upgrade is granted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
