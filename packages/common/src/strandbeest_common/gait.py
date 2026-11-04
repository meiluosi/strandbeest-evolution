"""Kinematic gait metrics through the required shared Rust kernel."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .linkage import LinkageSpec, _kernel


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
    trajectory = _kernel(spec).trace_trajectory(samples)
    return trajectory.points if trajectory.assembled else None


def gait_metrics(spec: LinkageSpec, samples: int = 180, tol: float = 0.015) -> Gait:
    result = _kernel(spec).compute_gait(samples, tol)
    return Gait(result.width, result.lift, result.stroke_length, result.duty, result.assembled)
