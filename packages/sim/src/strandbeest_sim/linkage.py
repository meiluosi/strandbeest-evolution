"""Linkage spec (exported from packages/core as JSON) and its kinematic solver (used for the initial pose)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Union

Point = tuple[float, float]  # (x forward, y up) in the hip frame, in length units

Ref = Union[str, float, int]


@dataclass(frozen=True)
class Joint:
    id: str
    centers: tuple[str, str]
    radii: tuple[Ref, Ref]
    side: int


@dataclass(frozen=True)
class LinkageSpec:
    params: dict[str, float]
    crank_x: Ref
    crank_y: Ref
    crank_length: Ref
    joints: tuple[Joint, ...]
    foot: str

    def val(self, ref: Ref) -> float:
        return float(ref) if isinstance(ref, (int, float)) else float(self.params[ref])

    @property
    def pivot(self) -> Point:
        return (self.val(self.crank_x), self.val(self.crank_y))

    @property
    def crank(self) -> float:
        return self.val(self.crank_length)


def load_spec(path_or_dict: Union[str, Path, dict]) -> LinkageSpec:
    d = path_or_dict if isinstance(path_or_dict, dict) else json.loads(Path(path_or_dict).read_text())
    c = d["crank"]
    return LinkageSpec(
        params=dict(d["params"]),
        crank_x=c["x"],
        crank_y=c["y"],
        crank_length=c["length"],
        joints=tuple(Joint(j["id"], tuple(j["centers"]), tuple(j["radii"]), int(j["side"])) for j in d["joints"]),
        foot=d["foot"],
    )


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
