"""Conventions (docs/CONVENTIONS.md section 4) on the Python solver."""

import math

import pytest

from strandbeest_common import Design, solve_pose
from strandbeest_common.schemas import schema_dir

SPEC = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json").spec


def foot(psi, direction):
    return solve_pose(SPEC, direction * psi)["F"]


def stance_dx(direction, n=720):
    pts = [foot(2 * math.pi * i / n, direction) for i in range(n)]
    lo = min(p[1] for p in pts)
    width = max(p[0] for p in pts) - min(p[0] for p in pts)
    return sum(pts[i + 1][0] - pts[i][0] for i in range(n - 1) if pts[i][1] < lo + 0.01 * width and pts[i + 1][1] < lo + 0.01 * width)


def test_crank_tip_follows_theta_counter_clockwise():
    px, py = SPEC.pivot
    for th in (0.0, 0.7, 2.0, 4.1):
        c = solve_pose(SPEC, th)["C"]
        assert c == pytest.approx((px + SPEC.crank * math.cos(th), py + SPEC.crank * math.sin(th)))


def test_stance_foot_moves_backward_for_direction_minus_one_and_forward_for_plus_one():
    assert stance_dx(-1) < 0
    assert stance_dx(+1) > 0  # sensitivity: flipping the sign flips the result
