"""Public linkage dataclasses and the required Rust kinematics adapter (no Python solver fallback)."""

from __future__ import annotations

import json
import beest_kernel
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

    def __getstate__(self):
        # Native handles are process-local and reconstructed after copy/pickle.
        return {key: value for key, value in self.__dict__.items() if key != "_native_kernel_cache"}

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


def _kernel_spec(spec: LinkageSpec) -> dict:
    """Adapt the public Python dataclass without caching its mutable params dictionary."""
    return {
        "params": spec.params,
        "crank_x": spec.crank_x, "crank_y": spec.crank_y, "crank_length": spec.crank_length,
        "joints": [{"id": j.id, "centers": j.centers, "radii": j.radii, "side": j.side} for j in spec.joints],
        "foot": spec.foot,
    }


def _kernel(spec: LinkageSpec):
    # Value key: params is intentionally mutable; identity-only caching would return stale poses.
    key = (tuple(spec.params.items()), spec.crank_x, spec.crank_y, spec.crank_length, spec.joints, spec.foot)
    cached = getattr(spec, "_native_kernel_cache", None)
    if cached is None or cached[0] != key:
        native = beest_kernel.Linkage(_kernel_spec(spec))
        cached = (key, native)
        object.__setattr__(spec, "_native_kernel_cache", cached)
    return cached[1]


def circle_intersection(p0: Point, r0: float, p1: Point, r1: float, side: int) -> Point | None:
    return beest_kernel.circle_intersection(p0, r0, p1, r1, side)


def solve_pose(spec: LinkageSpec, theta: float) -> dict[str, Point] | None:
    """Rust kernel: length units, hip frame, y up; None only for geometric non-assembly."""
    return _kernel(spec).solve_pose(theta)
