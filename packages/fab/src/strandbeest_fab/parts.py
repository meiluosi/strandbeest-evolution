"""Derive the physical parts of a walker from a Design.

Planar leg stacked along the axle: bars that share a pin, or that sweep through each other as the crank turns, must sit
in different layers. We assign layers by greedy graph colouring on that conflict relation and report the stack height.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString

from strandbeest_common import Design, solve_pose

GAP_MM = 0.6  # assumption: washer / spacer between layers
SWEEP_SAMPLES = 90


@dataclass
class Bar:
    key: str  # unique within a leg, e.g. "K0"
    label: str  # human name, e.g. "G-K"
    a: str  # linkage point at one end
    b: str  # linkage point at the other end
    length_mm: float  # centre-to-centre
    layer: int = 0


@dataclass
class LegPlan:
    bars: list[Bar]
    crank_mm: float
    pins: dict[str, list[int]] = field(default_factory=dict)  # linkage point -> layers of parts through it
    layers: int = 0


def _bars(design: Design) -> list[Bar]:
    spec, u = design.spec, design.walker["unit_m"] * 1000.0
    out: list[Bar] = []
    for j in spec.joints:
        for k, (c, r) in enumerate(zip(j.centers, j.radii)):
            out.append(Bar(f"{j.id}{k}", f"{c}-{j.id}", c, j.id, spec.val(r) * u))
    return out


def plan_leg(design: Design) -> LegPlan:
    spec = design.spec
    u = design.walker["unit_m"] * 1000.0
    width = design.mfg["bar_width_mm"]
    bars = _bars(design)
    crank = Bar("crank", "P-C", "P", "C", spec.crank * u)
    allp = bars + [crank]

    # sweep the crank once and record each part as a segment per angle (mm, hip frame)
    segs: dict[str, list[LineString]] = {b.key: [] for b in allp}
    for i in range(SWEEP_SAMPLES):
        th = 2 * math.pi * i / SWEEP_SAMPLES
        pose = solve_pose(spec, th)
        if pose is None:
            raise ValueError("linkage cannot assemble over a full crank revolution")
        pose = dict(pose)
        pose["P"] = spec.pivot
        for b in allp:
            pa, pb = pose[b.a], pose[b.b]
            segs[b.key].append(LineString([(pa[0] * u, pa[1] * u), (pb[0] * u, pb[1] * u)]))

    ends = {b.key: {b.a, b.b} for b in allp}

    def conflict(x: Bar, y: Bar) -> bool:
        if ends[x.key] & ends[y.key]:
            return True  # share a pin: stacked on the same axle
        return any(sx.distance(sy) < width for sx, sy in zip(segs[x.key], segs[y.key]))

    # greedy colouring, most-constrained first
    order = sorted(allp, key=lambda b: -sum(conflict(b, o) for o in allp if o is not b))
    assigned: dict[str, int] = {}
    for b in order:
        used = {assigned[o.key] for o in allp if o.key in assigned and conflict(b, o)}
        layer = 0
        while layer in used:
            layer += 1
        assigned[b.key] = layer
    for b in allp:
        b.layer = assigned[b.key]
    plan = LegPlan(bars=bars + [crank], crank_mm=crank.length_mm)
    plan.layers = 1 + max(b.layer for b in plan.bars)
    for b in plan.bars:
        for p in (b.a, b.b):
            plan.pins.setdefault(p, []).append(b.layer)
    return plan
