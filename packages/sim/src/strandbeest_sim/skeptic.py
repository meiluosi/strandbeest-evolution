"""The simulator skeptic (A-03): invariants a trustworthy run must satisfy, and a fuzzer that looks for runs that break them.

Single-run audit (`audit`, works on a Result or on a stored run's metrics and arrays):
  energy_closure       input work = dissipation + change of mechanical energy within 2 % (steady runs)
  loop_closure         no loop of the linkage open by more than 5 mm
  penetration          feet sink less than 5 mm
  stride_vs_kinematics on flat ground the stride per revolution is within 15 % of the no-slip kinematic stride
  support              on a walker with at least 4 legs some foot is on the ground for almost all of the steady time
Backend checks (`check_*`, need a built simulation):
  no_foot_foot_contacts    feet never touch each other (the "overlapping foot spheres" bug of 2026-10-05)
  window_invariance        metrics do not depend on how long the run is, because they use whole revolutions (the "partial
                           window" bug of 2026-10-05)
plus the backend contract (mirror symmetry, unit scaling, ...: strandbeest_sim.contract).

The checks that sit between two runs are the ones that catch bugs a single run cannot show. Thresholds are choices, not
physics, and each finding carries its numbers."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .config import SimConfig

ENERGY_RESIDUAL = 0.02
LOOP_OPEN_M = 0.005
PENETRATION_M = 0.005
STRIDE_TOLERANCE = 0.15
WINDOW_TOLERANCE = 0.04


@dataclass
class Finding:
    check: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.check}: {self.message}"


def audit(sc: SimConfig, metrics: dict[str, Any], series: dict[str, np.ndarray] | None = None, stalled: bool = False) -> list[Finding]:
    """Invariants of one finished run. `series` is optional; checks that need it are skipped without it."""
    out: list[Finding] = []
    steady = metrics.get("steady_window") == 1.0
    resid = metrics.get("energy_residual_share")
    if steady and resid is not None and abs(resid) > ENERGY_RESIDUAL:
        out.append(Finding("energy_closure", f"energy does not close: residual {resid:.1%} of the input work", {"residual_share": resid, "limit": ENERGY_RESIDUAL}))
    loop = metrics.get("max_loop_violation")
    if loop is not None and loop > LOOP_OPEN_M:
        out.append(Finding("loop_closure", f"a loop opened by {loop * 1000:.1f} mm", {"opening_m": loop, "limit_m": LOOP_OPEN_M}))
    pen = metrics.get("max_penetration")
    if pen is not None and pen > PENETRATION_M:
        out.append(Finding("penetration", f"feet sink {pen * 1000:.1f} mm", {"penetration_m": pen, "limit_m": PENETRATION_M}))
    stride = metrics.get("stride_per_rev")
    if sc.terrain.kind == "flat" and sc.drive.kind == "motor" and not stalled and stride is not None and stride == stride and isinstance(sc.linkage.spec, dict):
        from .events import nominal_stride_m

        nominal = nominal_stride_m(sc)
        if nominal and abs(stride / nominal - 1) > STRIDE_TOLERANCE:
            out.append(Finding("stride_vs_kinematics", f"stride is {stride / nominal:.0%} of the kinematic stride on flat ground", {"stride_m": stride, "nominal_m": nominal, "ratio": stride / nominal}))
    if series and "foot_normal" in series and sc.walker.legs >= 4 and steady:
        down = (np.asarray(series["foot_normal"]) > 1e-6).sum(axis=1)
        none_down = float((down == 0).mean())
        if none_down > 0.05:
            out.append(Finding("support", f"no foot touches the ground for {none_down:.0%} of the run", {"airborne_share": none_down}))
    return out


def check_no_foot_foot_contacts(sim: Any, steps: int = 2000) -> list[Finding]:
    """Settle the built walker and look at every contact: a foot touching another foot is a modelling bug."""
    be = sim.backend
    feet = set(sim.info.foot_names)
    pairs: set[tuple[str, str]] = set()
    for _ in range(steps // 100):
        be.step(100)
        for c in be.contacts():
            if c.geom1 in feet and c.geom2 in feet:
                pairs.add((c.geom1, c.geom2))
    return [Finding("no_foot_foot_contacts", f"{len(pairs)} pair(s) of feet collide with each other", {"pairs": sorted(pairs)[:5]})] if pairs else []


def check_window_invariance(run_fn: Callable[[float], dict[str, Any]], short: float = 3.0, long: float = 3.5) -> list[Finding]:
    """Run the same scenario for two lengths; the steady metrics must agree because the window is whole revolutions."""
    a, b = run_fn(short), run_fn(long)
    out = []
    for k in ("stride_per_rev", "mean_torque", "mean_speed"):
        x, y = a.get(k), b.get(k)
        if x and y and abs(x - y) > WINDOW_TOLERANCE * max(abs(x), abs(y)):
            out.append(Finding("window_invariance", f"{k} depends on the run length: {x:.5g} at {short:g} revolutions, {y:.5g} at {long:g}", {"metric": k, "short": x, "long": y, "relative": abs(x - y) / max(abs(x), abs(y))}))
    return out


def random_scenario(rng: random.Random, design: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A random design (lengths perturbed by up to 8 % through the guarded edit operations) and a random scene overrides."""
    from strandbeest_common.guard import default_problems
    from strandbeest_common.ops import GuardError, OpError, apply_op, make_op

    d = design
    for name in rng.sample(list(d["linkage"]["params"]), 4):
        try:
            d = apply_op(d, make_op("set_param", {"name": name, "value": d["linkage"]["params"][name] * rng.uniform(0.92, 1.08)}), (default_problems,)).design
        except (GuardError, OpError):
            continue
    d = apply_op(d, make_op("array_legs", {"legs": rng.choice([4, 6, 8])}), (default_problems,)).design
    scene = rng.choice(["flat", "flat", "slope", "bumps"])
    ov: dict[str, Any] = {"run": {"revolutions": 2.1, "settle": 0.4, "frame_rate": 0}}
    if scene == "slope":
        ov["terrain"] = {"kind": "slope", "slope_deg": rng.choice([2, 4, 6])}
    elif scene == "bumps":
        ov["terrain"] = {"kind": "bumps", "params": {"count": 6, "max_height": 0.004, "start": 0.15, "seed": rng.randrange(100)}}
    return d, ov


def fuzz(n: int, seed: int = 0, base_design: dict[str, Any] | None = None) -> list[tuple[dict[str, Any], list[Finding]]]:
    """Run n random walkers and audit each; returns the (scenario description, findings) of the runs that broke an invariant."""
    from strandbeest_common import Design
    from strandbeest_common.schemas import schema_dir

    from .from_design import scenario_from_design
    from .runner import run

    import json

    base = base_design or json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())
    rng = random.Random(seed)
    bad = []
    for _ in range(n):
        d, ov = random_scenario(rng, base)
        res = run(scenario_from_design(Design(d), ov))
        findings = audit(res.scenario, res.metrics, res.series, res.stalled)
        if findings:
            bad.append(({"legs": d["walker"]["legs"], "params": d["linkage"]["params"], "terrain": ov.get("terrain", {"kind": "flat"})}, findings))
    return bad
