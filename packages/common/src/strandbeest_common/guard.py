"""The validity guard (E3-02): can this design be built and moved at all? Kinematic part, twin of packages/core/src/guard.ts.

An operation is rejected when it introduces an error. Problems carry a level ("error" rejects, "warning" informs),
a stable code, a path and a message. Printability and collisions are checked on the server by
strandbeest_fab.guard.printable_problems, which reuses the fabrication checks.

Checks here (all on the design's linkage):
  structure       names refer to something, joints only use earlier points, bars have positive length (validity.py)
  cannot_assemble the linkage cannot close for some crank angle over a full turn
  branch_flip     a point jumps between samples: the foot, or a joint, swapped assembly branch (or the linkage fails to
                  close in a window narrower than the sampling step)
  The degrees of freedom are 1 by construction (a chain of dyads from the ground and the crank tip: every joint is fixed
  by two earlier points), and the structure checks reject the ways to break that.
"""

from __future__ import annotations

import math
from typing import Any

from .linkage import load_spec, solve_pose
from .schemas import validator
from .validity import structure_errors

SAMPLES = 72  # crank angles tested: every 5 degrees
JUMP_FRACTION = 0.2  # a point that moves more than this fraction of the leg's size between samples is a suspect ...
REFINE = 16  # ... which is re-examined at 16 times the resolution
FLIP_FRACTION = 0.1  # a suspect is a real flip only if it still jumps more than this fraction of the size at that resolution


def kinematic_problems(linkage: dict[str, Any]) -> list[dict[str, str]]:
    problems = [{"level": "error", **e} for e in structure_errors(linkage)]
    if problems:
        return problems  # nothing below makes sense on a broken structure
    spec = load_spec(linkage)
    poses = []
    failed: list[int] = []
    for i in range(SAMPLES):
        pose = solve_pose(spec, 2 * math.pi * i / SAMPLES)
        if pose is None:
            failed.append(i)
        poses.append(pose)
    if failed:
        deg = sorted({round(360 * i / SAMPLES) for i in failed})
        shown = ", ".join(str(d) for d in deg[:6]) + (" ..." if len(deg) > 6 else "")
        return [{"level": "error", "code": "cannot_assemble", "path": "linkage",
                 "message": f"the linkage cannot close at {len(failed)} of {SAMPLES} crank angles (degrees: {shown})"}]
    size = max(math.hypot(*p) for pose in poses for p in pose.values()) or 1.0
    # A point can move fast without flipping (near a dead point it moves like the square root of the crank angle). So a
    # big step between samples is only a suspect: refine it, and call it a flip if it is still a jump (or the linkage
    # does not close inside the interval, a window narrower than the sampling step).
    for i, (a, b) in enumerate(zip(poses, poses[1:] + poses[:1])):
        if max(math.dist(a[j], b[j]) for j in a) <= JUMP_FRACTION * size:
            continue
        sub = [solve_pose(spec, 2 * math.pi * (i + k / REFINE) / SAMPLES) for k in range(REFINE + 1)]
        if any(p is None for p in sub):
            return [{"level": "error", "code": "branch_flip", "path": "linkage",
                     "message": f"the linkage fails to close in a narrow window near {round(360 * i / SAMPLES)} degrees of crank angle"}]
        for jid in a:
            worst = max(math.dist(x[jid], y[jid]) for x, y in zip(sub, sub[1:]))
            if worst > FLIP_FRACTION * size:
                return [{"level": "error", "code": "branch_flip", "path": f"joints.{jid}",
                         "message": f"point {jid} still jumps {worst / size:.0%} of the leg size at {360 / SAMPLES / REFINE:.2f} degree resolution: the assembly branch flips"}]
    return []


def design_problems(design: dict[str, Any]) -> list[dict[str, str]]:
    return kinematic_problems(design["linkage"])


def schema_problems(design: dict[str, Any]) -> list[dict[str, str]]:
    """The design against schemas/design.schema.json (types, ranges, enums, no unknown fields)."""
    out = []
    for e in sorted(validator("design").iter_errors(design), key=lambda e: list(map(str, e.path))):
        path = ".".join(str(p) for p in e.path) or "<root>"
        out.append({"level": "error", "code": "schema", "path": path, "message": f"{path}: {e.message}"})
    return out


def default_problems(design: dict[str, Any]) -> list[dict[str, str]]:
    """Schema, then kinematics (the kinematic checks assume a well-formed linkage)."""
    schema = schema_problems(design)
    return schema if schema else design_problems(design)
