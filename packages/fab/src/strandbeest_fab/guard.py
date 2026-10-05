"""Printability part of the validity guard (E3-02): the fabrication checks, as guard problems.

A failed check is an error (an operation that would make a printable design unprintable is rejected), a warning check is
a warning. Collisions between moving bars are avoided by construction: `plan_leg` sweeps the crank once and puts any two
bars that pass within a bar width of each other (or share a pin) into different layers, so bars on one layer never touch.
What the guard does not check: the legs against the frame, the body, the ground clearance of the swing phase."""

from __future__ import annotations

import re
from typing import Any

from strandbeest_common import Design

from .checks import run_checks
from .parts import axle_plan, plan_leg

TALL_STACK_LAYERS = 5  # more layers than this makes a tall, flexible leg stack


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def printable_problems(design: dict[str, Any]) -> list[dict[str, str]]:
    try:
        d = Design(design)
        plan = plan_leg(d)
        checks = run_checks(d, plan, axle_plan(d, plan))
    except Exception:  # noqa: BLE001  a broken linkage is reported by the kinematic guard; do not report it twice
        return []
    out = []
    for c in checks:
        if c.status != "pass":
            level = "error" if c.status == "fail" else "warning"
            out.append({"level": level, "code": f"not_printable.{_slug(c.name)}", "path": "manufacturing",
                        "message": f"{c.name}: {c.value} (needs {c.limit}). {c.note}".strip()})
    if plan.layers > TALL_STACK_LAYERS:
        out.append({"level": "warning", "code": "tall_stack", "path": "linkage",
                    "message": f"the leg needs {plan.layers} layers; stacks above {TALL_STACK_LAYERS} are tall and flexible"})
    return out
