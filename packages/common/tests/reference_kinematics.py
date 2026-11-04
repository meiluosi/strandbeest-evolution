"""Frozen pre-Rust reference, used only for independent migration parity and timing.
Production must never fall back to this implementation.
"""
from __future__ import annotations
import math
from strandbeest_common.linkage import LinkageSpec, Point
from strandbeest_common.gait import Gait

def circle_intersection(p0: Point, r0: float, p1: Point, r1: float, side: int) -> Point | None:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy)
    if d == 0 or d > r0 + r1 or d < abs(r0 - r1):
        return None
    a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r0 * r0 - a * a))
    mx, my = p0[0] + a * dx / d, p0[1] + a * dy / d
    return (mx - side * h * dy / d, my + side * h * dx / d)


def solve_pose(spec: LinkageSpec, theta: float) -> dict[str, Point] | None:
    """All joint positions (length units, hip frame, y up) for crank angle theta, or None if it cannot assemble."""
    px, py = spec.pivot
    pose: dict[str, Point] = {
        "G": (0.0, 0.0),
        "C": (px + spec.crank * math.cos(theta), py + spec.crank * math.sin(theta)),
    }
    for j in spec.joints:
        p = circle_intersection(pose[j.centers[0]], spec.val(j.radii[0]), pose[j.centers[1]], spec.val(j.radii[1]), j.side)
        if p is None:
            return None
        pose[j.id] = p
    return pose


def foot_path(spec: LinkageSpec, samples: int = 180) -> list[tuple[float, float]] | None:
    out = []
    for i in range(samples):
        pose = solve_pose(spec, 2 * math.pi * i / samples)
        if pose is None:
            return None
        out.append(pose[spec.foot])
    return out


def gait_metrics(spec: LinkageSpec, samples: int = 180, tol: float = 0.015) -> Gait:
    path = foot_path(spec, samples)
    if path is None:
        return Gait(0.0, 0.0, 0.0, 0.0, assembled=False)
    xs, ys = [p[0] for p in path], [p[1] for p in path]
    lo = min(ys)
    width, lift = max(xs) - min(xs), max(ys) - lo
    limit = lo + tol * width
    on = [y <= limit for y in ys]
    n = len(path)
    if all(on):
        return Gait(width, lift, width, 1.0)
    best, best_start, run, run_start = 0, 0, 0, 0
    for i in range(2 * n):  # walk twice so a run crossing index 0 is counted whole
        if on[i % n]:
            if run == 0:
                run_start = i
            run += 1
            if best < run <= n:
                best, best_start = run, run_start
        else:
            run = 0
    if best == 0:
        return Gait(width, lift, 0.0, 0.0)
    seg = [path[(best_start + i) % n][0] for i in range(best)]
    return Gait(width, lift, max(seg) - min(seg), best / n)
