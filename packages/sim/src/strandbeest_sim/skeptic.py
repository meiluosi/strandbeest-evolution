"""The simulator skeptic (A-03): invariants a trustworthy run must satisfy, and a fuzzer that looks for runs that break them.

Version-2 audit (`audit`, full report in audit.audit_report), with unchanged
numeric thresholds and explicit unverified reference applicability (ADR-0012):
  energy_closure       input work = dissipation + change of mechanical energy within 2 % (steady runs)
  loop_closure         no loop of the linkage open by more than 5 mm
  penetration          feet sink less than 5 mm
  stride_vs_kinematics signed stride is within 15 % only when the ideal model's conditions are verified
  stride_reference_unverified missing applicability or independent validation never counts as a pass
  support              on a walker with at least 4 legs some foot is on the ground for almost all of the steady time
Backend checks (`check_*`, need a built simulation):
  no_foot_foot_contacts    feet never touch each other (the "overlapping foot spheres" bug of 2026-10-05)
  window_invariance        metrics do not depend on how long the run is, because they use whole revolutions (the "partial
                           window" bug of 2026-10-05)
plus the backend contract (mirror symmetry, unit scaling, ...: strandbeest_sim.contract).

The checks that sit between two runs are the ones that catch bugs a single run cannot show. Thresholds are choices, not
physics, and each finding carries its numbers. audit_legacy preserves version 1
for comparison and historical experiment reproduction."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from numbers import Real
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


def _finite_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(value)


def _evidence_value(value: Any) -> Any:
    """Keep even a non-finite finding serializable as strict JSON."""
    if _finite_number(value):
        return float(value)
    if value is None or isinstance(value, (str, bool)):
        return value
    return str(value)


def audit_legacy(sc: SimConfig, metrics: dict[str, Any], series: dict[str, np.ndarray] | None = None, stalled: bool = False) -> list[Finding]:
    """Version 1, retained unchanged for historical comparisons (ADR-0012).

    Missing or non-finite required metrics produce `audit_evidence`, not a pass.
    `series=None` explicitly requests a metrics-only audit. Supplied support
    series must be nonempty, finite and have one load column per leg.
    """
    out: list[Finding] = []

    def metric(name: str, *, nonnegative: bool = False) -> float | None:
        value = metrics.get(name)
        if not _finite_number(value) or (nonnegative and value < 0):
            out.append(Finding("audit_evidence", f"{name} is missing or invalid; its invariant cannot be verified",
                               {"metric": name, "value": _evidence_value(value),
                                "required": "finite nonnegative number" if nonnegative else "finite number"}))
            return None
        return float(value)

    window = metric("steady_window")
    if window is not None and window not in (0.0, 1.0):
        out.append(Finding("audit_evidence", "steady_window must be 0 or 1",
                           {"metric": "steady_window", "value": window, "required": "0 or 1"}))
    steady = window == 1.0
    resid = metric("energy_residual_share") if steady else None
    if steady and resid is not None and abs(resid) > ENERGY_RESIDUAL:
        out.append(Finding("energy_closure", f"energy does not close: residual {resid:.1%} of the input work", {"residual_share": resid, "limit": ENERGY_RESIDUAL}))
    loop = metric("max_loop_violation", nonnegative=True)
    if loop is not None and loop > LOOP_OPEN_M:
        out.append(Finding("loop_closure", f"a loop opened by {loop * 1000:.1f} mm", {"opening_m": loop, "limit_m": LOOP_OPEN_M}))
    pen = metric("max_penetration", nonnegative=True)
    if pen is not None and pen > PENETRATION_M:
        out.append(Finding("penetration", f"feet sink {pen * 1000:.1f} mm", {"penetration_m": pen, "limit_m": PENETRATION_M}))
    if sc.terrain.kind == "flat" and sc.drive.kind == "motor" and not stalled:
        from .events import nominal_stride_m

        stride = metric("stride_per_rev")
        try:
            nominal = nominal_stride_m(sc)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            nominal = None
            out.append(Finding("audit_evidence", "the kinematic stride reference could not be resolved",
                               {"metric": "nominal_stride_m", "error": str(exc)}))
        if not _finite_number(nominal) or nominal == 0:
            if not any(f.evidence.get("metric") == "nominal_stride_m" for f in out):
                out.append(Finding("audit_evidence", "the kinematic stride reference is undefined or zero",
                                   {"metric": "nominal_stride_m", "value": _evidence_value(nominal)}))
        elif stride is not None and abs(stride / nominal - 1) > STRIDE_TOLERANCE:
            out.append(Finding("stride_vs_kinematics", f"stride is {stride / nominal:.0%} of the kinematic stride on flat ground", {"stride_m": stride, "nominal_m": nominal, "ratio": _evidence_value(stride / nominal)}))
    if series is not None and sc.walker.legs >= 4:
        try:
            normal = np.asarray(series.get("foot_normal"))
            valid = (normal.ndim == 2 and normal.shape[0] > 0 and normal.shape[1] == sc.walker.legs
                     and np.issubdtype(normal.dtype, np.number) and not np.iscomplexobj(normal)
                     and np.isfinite(normal).all() and (normal >= 0).all())
        except (ValueError, TypeError):
            valid = False
        if not valid:
            out.append(Finding("audit_evidence", "foot support samples are missing or invalid",
                               {"metric": "foot_normal", "required": "nonempty finite nonnegative [samples, legs] array",
                                "legs": sc.walker.legs}))
        elif steady:
            down = (normal > 1e-6).sum(axis=1)
            none_down = float((down == 0).mean())
            if none_down > 0.05:
                out.append(Finding("support", f"no foot touches the ground for {none_down:.0%} of the run", {"airborne_share": none_down}))
    return out


def audit(sc: SimConfig, metrics: dict[str, Any], series: dict[str, np.ndarray] | None = None,
          stalled: bool = False, *, backend_name: str | None = None, observation: dict | None = None,
          independent_validation: dict | None = None) -> list[Finding]:
    """Version 2 findings: missing applicability is not a successful audit.

    Use audit_report for the version, scoped status and full legacy comparison.
    """
    from .audit import audit_report

    report = audit_report(sc, metrics, series, stalled, backend_name=backend_name,
                          observation=observation, independent_validation=independent_validation)
    return [Finding(**f) for f in report['findings']]


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
        if not _finite_number(x) or not _finite_number(y):
            out.append(Finding("window_invariance", f"{k} is missing or non-finite in a comparison window",
                               {"metric": k, "short": _evidence_value(x), "long": _evidence_value(y),
                                "reason": "finite metrics are required in both windows"}))
        else:
            scale = max(abs(x), abs(y))
            relative = abs(x / scale - y / scale) if scale else 0.0
            if relative > WINDOW_TOLERANCE:
                out.append(Finding("window_invariance", f"{k} depends on the run length: {x:.5g} at {short:g} revolutions, {y:.5g} at {long:g}", {"metric": k, "short": float(x), "long": float(y), "relative": float(relative)}))
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
        findings = audit(res.scenario, res.metrics, {"t": res.t, "psi": res.psi, "x": res.x, **res.series},
                         res.stalled, backend_name="mujoco", observation=res.audit_observation)
        if findings:
            bad.append(({"legs": d["walker"]["legs"], "params": d["linkage"]["params"], "terrain": ov.get("terrain", {"kind": "flat"})}, findings))
    return bad
