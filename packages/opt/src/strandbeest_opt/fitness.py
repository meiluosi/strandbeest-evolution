"""Kinematic fitness functions over a GenomeSpace: Python port of packages/core/src/fitness.ts, checked against the TypeScript
values in contracts/fitness/cases.json (to 1e-9). Higher is better; infeasible legs get a graded penalty in [-10, -4)."""

from __future__ import annotations

import math
from typing import Callable

from strandbeest_common.gait import foot_path, gait_metrics
from strandbeest_common.linkage import solve_pose

from .space import GenomeSpace

MAX_STEP_RATIO = 0.25  # a foot that jumps more than this fraction of its path width between samples flipped branch
INFEASIBLE = -4.0
PROBES = 24
SAMPLES = 90

Fitness = Callable[[list[float]], float]


def infeasibility(space: GenomeSpace, genome) -> float | None:
    """Graded penalty in [-10, -4) for a leg that cannot assemble, flips, or rises above the hip; None when feasible."""
    spec = space.to_spec(genome)
    ok = sum(1 for i in range(PROBES) if solve_pose(spec, 2 * math.pi * i / PROBES) is not None)
    if ok < PROBES:
        return -10 + 5 * (ok / PROBES)
    foot = foot_path(spec, SAMPLES)
    assert foot is not None
    m = gait_metrics(spec, SAMPLES)
    below_hip = sum(1 for p in foot if p[1] < 0) / len(foot)
    max_step = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(foot, foot[1:] + foot[:1]))
    flipped = m.width <= 0 or max_step > MAX_STEP_RATIO * m.width
    if below_hip < 1 or flipped:
        return -5 + 0.9 * below_hip - (0.05 if flipped else 0.0)
    return None


def leg_metrics(space: GenomeSpace, genome):
    if infeasibility(space, genome) is not None:
        return None
    return gait_metrics(space.to_spec(genome), SAMPLES)


def fitness_flat_stroke(space: GenomeSpace) -> Fitness:
    """A walking gait needs a flat ground stroke AND a real swing phase: lift below 15 % of the width is rejected, duty counts
    up to 0.6, score = min(duty, 0.6) * (1 + min(lift/width, 0.4)) * (stroke/width)."""

    def f(genome) -> float:
        m = leg_metrics(space, genome)
        if m is None:
            return infeasibility(space, genome)  # type: ignore[return-value]
        ratio = m.lift / m.width
        if ratio < 0.15:
            return ratio - 1
        return min(m.duty, 0.6) * (1 + min(ratio, 0.4)) * (m.stroke_length / m.width)

    return f


def fitness_high_step(space: GenomeSpace, min_duty: float = 0.35) -> Fitness:
    def f(genome) -> float:
        m = leg_metrics(space, genome)
        if m is None:
            return infeasibility(space, genome)  # type: ignore[return-value]
        if m.duty < min_duty:
            return m.duty - min_duty - 1
        return m.lift / m.width

    return f
