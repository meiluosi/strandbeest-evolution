"""Kinematic gait metrics of a Design's foot path (Python port of packages/core gaitMetrics)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .linkage import LinkageSpec, solve_pose


@dataclass
class Gait:
    width: float  # foot loop extent in x, length units
    lift: float  # foot loop extent in y
    stroke_length: float  # x-span of the flat ground stroke
    duty: float  # fraction of the cycle on the ground stroke
    assembled: bool = True

    def asdict(self) -> dict:
        return asdict(self)


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
