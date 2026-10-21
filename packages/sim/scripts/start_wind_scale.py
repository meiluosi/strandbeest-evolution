"""W-05: the start wind as a function of the geometric scale factor (the flagship experiment of docs/WIND.md section 3).

One design family (the small 6-leg Jansen walker) is scaled geometrically by L and its start wind is searched again, for
several mass exponents p. Scaling rules (geometric consistency, see `scale_overrides`):

  * every length scales with L: the linkage is stored in length units, so `walker.unit` x L scales every link;
    `body_length`, `lateral_spacing` and the foot radius follow;
  * every mass scales with L**p: `walker.body_mass` x L**p, and `walker.tube_mass_per_m` x L**(p-1) so that a bar's mass
    (tube_mass_per_m x length) also scales as L**p;
  * the sail scales with the geometry: `sail_area` x L**2, `sail_radius` x L, `sail_gear` unchanged (it is dimensionless: it
    only multiplies the crank torque, see strandbeest_sim/drives.py);
  * the settle-phase servo gains and its torque limit scale as L**(p+1), i.e. with the load torque they have to hold, so the
    settling transient does not change with the scale (otherwise the crank sags during settle: a servo artifact, not physics);
  * `manufacturing.bar_width_mm` / `bar_thickness_mm` only feed `Design.bar_mass_per_m()`; because `tube_mass_per_m` is
    overridden above, the printed-bar cross-section becomes moot for the mass (it is still used for the visual bar radius).

Everything else keeps the scenario default, which is stated in the write-up: `crank_friction` (0.002 N*m), `crank_damping`
(0.001 N*m*s/rad) and `rotor_inertia` (1e-4 kg*m^2) are absolute values and do NOT scale with L; `joint_friction` and
`joint_damping` default to 0 (ideal pins); `body_drag_area` stays 0 (no chassis drag).

The start wind is the one of W-03: the lowest constant wind at which the crank completes one revolution within 40 s, found by
bracket-by-doubling plus geometric bisection to 5 % (packages/sim/src/strandbeest_sim/startwind.py). The result is always an
interval (lo, hi]; a cell that cannot start even at 30 m/s is recorded with hi = inf (docs/WIND.md section 6, rule 3).

Usage: python scripts/start_wind_scale.py out.json [workers] [--scales ...] [--mass-exponents ...] [--friction-scales ...]
                                                     [--frictions ...] [--max-time 40] [--no-k2]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design, sim_config
from strandbeest_sim.startwind import MAX_TIME_S, find_start_wind, simulate_attempt

DESIGN_NAME = "design-jansen-small-6leg.json"

# The reference measurement of the unscaled walker (EXPERIMENTS.md section 28, W-03): the interval (0.479, 0.500] m/s.
# It is the anchor the pre-registered prediction is normalised at; the prediction itself is derived from the code (below).
V_REF_M_S = 0.489

# Default protocol (the full one). A shorter list is used when the wall clock does not allow the full sweep.
DEFAULT_SCALES = (0.25, 0.35, 0.5, 0.7, 1.0, 1.4, 2.0, 2.8, 4.0)
DEFAULT_MASS_EXPONENTS = (1.0, 2.0, 3.0)
DEFAULT_FRICTION_SCALES = (0.25, 0.5, 1.0, 2.0)
DEFAULT_FRICTIONS = (0.0, 0.0005, 0.002)
K2_SCALES = (1.0, 2.0)
# the "does not start" probe: below L = 0.25 the absolute pin friction dominates and the machine cannot start at all
PROBE_CELLS = ((0.1, 1.0, 0.002),)


def make_executor(workers: int) -> ProcessPoolExecutor:
    """A process pool, with a shim for sandboxes that refuse os.sysconf('SC_SEM_NSEMS_MAX').

    The check inside ProcessPoolExecutor is a sanity check on the number of available semaphores; some sandboxes deny the
    sysconf call while the semaphores themselves work. The shim only skips the check.
    """
    try:
        os.sysconf("SC_SEM_NSEMS_MAX")
    except (AttributeError, OSError, ValueError):
        import concurrent.futures.process as _fp

        _fp._check_system_limits = lambda: None  # noqa: SLF001
    return ProcessPoolExecutor(max_workers=max(1, workers))


def design() -> Design:
    """The base design (L = 1)."""
    return Design.load(schema_dir() / "examples" / DESIGN_NAME)


def base_config():
    """The flat scenario configuration of the base design (the values the scaling is derived from)."""
    return sim_config(scenario_from_design(design()))


def scale_overrides(base, L: float, p: float, *, joint_friction: float = 0.0) -> dict[str, Any]:
    """Scenario overrides that scale the base design geometrically by L with the mass exponent p.

    Pure function of the base configuration: every returned value is the base value times its scaling law.
    """
    w, d = base.walker, base.drive
    return {
        "walker": {
            "unit": w.unit * L,  # every link length (the linkage is in length units)
            "body_mass": w.body_mass * L**p,  # the torso mass
            "tube_mass_per_m": w.tube_mass_per_m * L ** (p - 1),  # a bar's mass = tube_mass_per_m x length ~ L**p
            "min_bar_mass": w.min_bar_mass * L**p,  # the floor on a bar's mass follows, so it never clips the scaling
            "lateral_spacing": w.lateral_spacing * L,
            "body_length": w.body_length * L,
            "foot_radius": w.foot_radius * L,
            "joint_friction": joint_friction,  # absolute Coulomb torque per pin (assumption, 0 = ideal)
        },
        "drive": {
            "sail_area": d.sail_area * L**2,  # the sail force is proportional to the area
            "sail_radius": d.sail_radius * L,  # the moment arm of the sail on the crank
            "sail_gear": d.sail_gear,  # dimensionless: it multiplies the crank torque, so it does not change an exponent
            "kp": d.kp * L ** (p + 1),  # the settle-phase servo holds the weight: its gain scales with the load torque
            "kv": d.kv * L ** (p + 1),
            "max_torque": d.max_torque * L ** (p + 1),
        },
    }


def predicted_slope(p: float, load_model: str = "lift") -> float:
    """The pre-registered log-log slope d log(v_start) / d log(L) of the start wind.

    `load_model` names the load that dominates the crank:

    * "lift": the crank torque has to raise the machine. Every mass scales as L**p and the moment arm of the weight about
      the crank scales as L, so the load torque is proportional to L**(p+1). The sail torque is
      gear * 0.5 * rho * Cd * A * r * v**2 with A ~ L**2 and r ~ L, so it is proportional to L**3 * v**2.
      Balancing the two: v ~ L**((p-2)/2).
    * "pin_friction_weight": WIND.md section 4 states that the pin friction scales with the normal force, i.e. with the
      weight: the friction force is proportional to L**p and its moment arm to L, so the friction torque is again
      proportional to L**(p+1) and the slope is the same as "lift".
    * "pin_friction_absolute": the model as it is coded: `walker.joint_friction` is an absolute Coulomb torque per pin
      (MuJoCo frictionloss), so it does not grow with the weight: the friction torque is independent of L. A friction
      dominated threshold needs L**3 * v**2 ~ const, i.e. v**2 ~ const / L**3, i.e. v ~ L**(-1.5).
      (Sign correction, 2026-10-21: the pre-registration wrote this exponent as +1.5; the algebra gives -1.5, because
      the balance is L**3 * v**2 = const, so v = sqrt(const) * L**(-3/2). A smaller machine needs MORE wind. The
      qualitative statement in the pre-registration ("a small machine is stuck by the absolute pin friction") was
      already the one of the corrected exponent; only the sign of the number was wrong.)
    * "time_criterion": the "one revolution within 40 s" criterion. The crank has to keep turning at
      omega_req = 2*pi/T, and the sail torque drops with the crank speed (rel = v - omega * gear * r), so the threshold
      carries the extra term omega_req * gear * r, which is proportional to L.
    """
    if load_model in ("lift", "pin_friction_weight"):
        return (p - 2.0) / 2.0
    if load_model == "pin_friction_absolute":
        return -1.5
    if load_model == "time_criterion":
        return 1.0
    raise ValueError(f"unknown load model {load_model!r}")


def predicted_start_wind(
    L: float,
    p: float,
    *,
    v_ref: float = V_REF_M_S,
    max_time_s: float = MAX_TIME_S,
    gear: float | None = None,
    sail_radius: float | None = None,
) -> float:
    """The pre-registered prediction of the start wind at scale L and mass exponent p.

    Two terms, both derived from the code:

        v(L) = A * L**((p-2)/2) + B * L

    * A = sqrt(load torque / (gear * 0.5 * rho * Cd * A * r)) is the quasi-static threshold: the load torque is L**(p+1) and
      the sail torque is L**3 * v**2, so the static part scales as L**((p-2)/2).
    * B = omega_req * gear * r is the extra wind the crank speed costs: the sail torque falls with the crank speed
      (rel = v - omega * gear * r), and one revolution within T seconds needs omega_req = 2*pi/T.

    A and B are normalised at L = 1 with the published W-03 measurement of the unscaled walker (v_ref), so the prediction is
    a shape, not an independent absolute claim. At L = 1 the prediction returns v_ref.
    """
    if gear is None or sail_radius is None:
        cfg = base_config()
        gear = cfg.drive.sail_gear if gear is None else gear
        sail_radius = cfg.drive.sail_radius if sail_radius is None else sail_radius
    b = (2.0 * math.pi / max_time_s) * gear * sail_radius
    a = v_ref - b
    return a * L ** ((p - 2.0) / 2.0) + b * L


def log_log_slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of log(y) against log(x)."""
    pts = [(math.log(x), math.log(y)) for x, y in zip(xs, ys) if x > 0 and y > 0 and math.isfinite(y)]
    if len(pts) < 2:
        return float("nan")
    n = len(pts)
    mx = sum(a for a, _ in pts) / n
    my = sum(b for _, b in pts) / n
    den = sum((a - mx) ** 2 for a, _ in pts)
    if den <= 0:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in pts) / den


def cell_key(scale: float, mass_exponent: float, friction: float, backend: str) -> str:
    """The identity of one cell of the sweep (used to resume a partially finished run)."""
    return f"{backend}|L={scale:g}|p={mass_exponent:g}|jf={friction:g}"


def detail_attempt(design_obj: Design, overrides: dict[str, Any], backend: str, *, max_time: float) -> dict[str, Any]:
    """One attempt that also reports how far the crank got (for the "does not start" records)."""
    ov = {k: dict(v) for k, v in overrides.items()}
    ov.setdefault("drive", {})["kind"] = "sail"
    ov["wind"] = {**ov.get("wind", {}), "kind": "constant"}
    ov["run"] = {**ov.get("run", {}), "revolutions": 1.0, "settle": 0.5, "max_time": max_time, "frame_rate": 0}
    from strandbeest_sim import run as run_scenario  # local import keeps the module import cheap

    r = run_scenario(scenario_from_design(design_obj, ov), backend=backend)
    return {
        "started": not r.stalled,
        "time_s": float(r.t[-1]) if len(r.t) else 0.0,
        "distance_m": float(r.x[-1] - r.x[0]) if len(r.x) else 0.0,
        "crank_rad": float(r.psi[-1] - r.psi[0]) if len(r.psi) else 0.0,
        "valid": bool(r.metrics["max_loop_violation"] < 0.0017),
    }


def run_cell(job: dict[str, Any]) -> dict[str, Any]:
    """One cell of the sweep: search the start wind of the scaled design."""
    scale = float(job["scale"])
    p = float(job["mass_exponent"])
    friction = float(job["joint_friction"])
    backend = str(job["backend"])
    max_time = float(job["max_time_s"])
    base = base_config()
    overrides = scale_overrides(base, scale, p, joint_friction=friction)
    guess = float(job["guess"])

    t0 = time.time()
    r = find_start_wind(
        simulate_attempt(design(), overrides, backend=backend, max_time=max_time, give_up=10.0),
        guess=guess,
        rel_tol=0.05,
    )
    wall = time.time() - t0

    out: dict[str, Any] = {
        "key": cell_key(scale, p, friction, backend),
        "scale": scale,
        "mass_exponent": p,
        "joint_friction_nm": friction,
        "backend": backend,
        "lo_m_s": r.lo,
        "hi_m_s": r.hi,
        "estimate_m_s": r.estimate,
        "found": r.found,
        "trusted": r.trusted,
        "does_not_start": (not r.found) and math.isinf(r.hi),
        "simulations": len(r.runs),
        "note": r.note,
        "max_wind_tried_m_s": max((x["wind"] for x in r.runs), default=0.0),
        "runs": r.runs,
        "predicted_m_s": predicted_start_wind(scale, p),
    }
    if out["does_not_start"]:
        # the numbers behind "it does not move": one more attempt at the highest wind that was tried
        d = detail_attempt(design(), overrides, backend, max_time=max_time)
        out["does_not_start_detail"] = {**d, "at_wind_m_s": out["max_wind_tried_m_s"]}
    out["_wall_time_s"] = wall
    print(
        f"[{out['key']}] ({r.lo:.4g}, {r.hi:.4g}] m/s"
        f"{'' if r.found else '  DOES NOT START'}  {len(r.runs)} sims  {wall / 60:.1f} min",
        flush=True,
    )
    return out


def build_jobs(
    scales: tuple[float, ...],
    mass_exponents: tuple[float, ...],
    friction_scales: tuple[float, ...],
    frictions: tuple[float, ...],
    backend: str,
    k2_scales: tuple[float, ...],
    max_time_s: float,
    probe_cells: tuple[tuple[float, float, float], ...] = PROBE_CELLS,
) -> list[dict[str, Any]]:
    """The deterministic job list. The cells of the friction band at friction = 0 are the cells of the main sweep."""
    jobs: dict[str, dict[str, Any]] = {}

    def add(scale: float, p: float, friction: float, be: str, alias_of: str | None = None) -> None:
        key = cell_key(scale, p, friction, be)
        if key in jobs:
            return
        guess = predicted_start_wind(scale, p)
        job = {
            "key": key,
            "scale": scale,
            "mass_exponent": p,
            "joint_friction": friction,
            "backend": be,
            "max_time_s": max_time_s,
            "guess": max(0.02, guess),
        }
        if alias_of is not None:
            job["alias_of"] = alias_of
        jobs[key] = job

    # The L = 1 anchors come first: they are the self-check. At L = 1 the scaled design is the base design for every
    # mass exponent (L**p = 1 for any p, asserted by test_L_one_changes_nothing), so only the first exponent is
    # simulated; the other L = 1 cells are aliases of that one cell and cost nothing.
    for i, p in enumerate(mass_exponents):
        if i == 0:
            add(1.0, p, 0.0, backend)
        else:
            add(1.0, p, 0.0, backend, alias_of=cell_key(1.0, mass_exponents[0], 0.0, backend))

    # The main sweep, scale by scale: p = 1 (the realistic thin wall case) and p = 3 (the solid body) at the same scale
    # are neighbours, and the friction band of that scale follows them. A run that is cut short therefore leaves
    # partial but balanced curves *and* a partial band, instead of a full curve and no band.
    for s in scales:
        for p in (1.0, 3.0, 2.0):
            if p not in mass_exponents:
                continue
            add(s, p, 0.0, backend)
        if s in friction_scales:
            for f in frictions:
                if f != 0.0:
                    add(s, 1.0, f, backend)
    # any friction cell whose scale is not part of the main sweep
    for s in friction_scales:
        if s in scales:
            continue
        for f in frictions:
            if f != 0.0:
                add(s, 1.0, f, backend)
    # the "does not start" probe, then the K2 cross-check (cheap, and it must not be silently dropped)
    for scale, p, friction in probe_cells:
        add(scale, p, friction, backend)
    for s in k2_scales:
        add(s, 1.0, 0.0, "k2")
    return list(jobs.values())


def resolve_aliases(cells: list[dict[str, Any]], jobs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Add / fill in the alias cells: they carry the numbers of the cell they point at.

    An alias exists because the scaled design at L = 1 does not depend on the mass exponent: the L = 1 cell of p = 2
    and p = 3 is physically the same simulation as the L = 1 cell of p = 1, so it is recorded as the same numbers
    with the key of the exponent, flagged by `alias_of`. An alias whose source is missing is dropped (it is then
    re-created by the next run).
    """
    by_key = {c["key"]: c for c in cells}
    out: list[dict[str, Any]] = []
    for c in cells:
        src = c.get("alias_of")
        if not src:
            out.append(c)
            continue
        source = by_key.get(src)
        if source is None:
            continue
        out.append(
            {
                **source,
                "key": c["key"],
                "scale": c["scale"],
                "mass_exponent": c["mass_exponent"],
                "alias_of": src,
                "note": f"the same physical cell as {src}: at L = 1 the scaled design does not depend on p",
            }
        )
    # the alias cells are not simulated, so they have to be built from the job list
    for job in jobs or []:
        src = job.get("alias_of")
        key = job["key"]
        if not src or key in by_key:
            continue
        source = by_key.get(src)
        if source is None:
            continue
        out.append(
            {
                **source,
                "key": key,
                "scale": job["scale"],
                "mass_exponent": job["mass_exponent"],
                "alias_of": src,
                "note": f"the same physical cell as {src}: at L = 1 the scaled design does not depend on p",
            }
        )
    return out


def merge_cells(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the cells of two runs, keeping the first result for a key (deterministic)."""
    merged: dict[str, dict[str, Any]] = {}
    for c in list(old) + list(new):
        merged.setdefault(c["key"], c)
    return list(merged.values())


def summarise(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """The curves, the measured slopes and the minimum viable scale."""
    out: dict[str, Any] = {"curves": {}, "slopes": {}, "does_not_start": []}
    by_p: dict[float, list[dict[str, Any]]] = {}
    for c in cells:
        if c["backend"] != "mujoco":
            continue
        by_p.setdefault(float(c["mass_exponent"]), []).append(c)
    for p, rows in by_p.items():
        rows = sorted(rows, key=lambda c: c["scale"])
        zero = [r for r in rows if r["joint_friction_nm"] == 0.0]
        zero.sort(key=lambda c: c["scale"])
        out["curves"][f"p={p:g}"] = [
            {"scale": r["scale"], "lo_m_s": r["lo_m_s"], "hi_m_s": r["hi_m_s"], "estimate_m_s": r["estimate_m_s"],
             "found": r["found"], "simulations": r["simulations"], "predicted_m_s": r["predicted_m_s"]}
            for r in zero
        ]
        xs = [r["scale"] for r in zero if r["found"]]
        ys = [r["estimate_m_s"] for r in zero if r["found"]]
        out["slopes"][f"p={p:g}"] = {
            "measured": log_log_slope(xs, ys),
            "predicted_lift": predicted_slope(p, "lift"),
            "predicted_pin_friction_weight": predicted_slope(p, "pin_friction_weight"),
            "predicted_pin_friction_absolute": predicted_slope(p, "pin_friction_absolute"),
        }
    for c in cells:
        if c.get("does_not_start"):
            out["does_not_start"].append(
                {
                    "key": c["key"],
                    "scale": c["scale"],
                    "mass_exponent": c["mass_exponent"],
                    "joint_friction_nm": c["joint_friction_nm"],
                    "max_wind_tried_m_s": c["max_wind_tried_m_s"],
                    "simulations": c["simulations"],
                    "detail": c.get("does_not_start_detail"),
                    "note": c["note"],
                }
            )
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="W-05: the start wind as a function of the geometric scale factor")
    ap.add_argument("out", help="the JSON file to write")
    ap.add_argument("workers", nargs="?", type=int, default=4, help="number of parallel worker processes")
    ap.add_argument("--scales", default=",".join(f"{s:g}" for s in DEFAULT_SCALES), help="comma separated scale factors L")
    ap.add_argument("--mass-exponents", default=",".join(f"{p:g}" for p in DEFAULT_MASS_EXPONENTS), help="comma separated p")
    ap.add_argument("--friction-scales", default=",".join(f"{s:g}" for s in DEFAULT_FRICTION_SCALES), help="comma separated L of the friction band")
    ap.add_argument("--frictions", default=",".join(f"{f:g}" for f in DEFAULT_FRICTIONS), help="comma separated joint_friction in N*m")
    ap.add_argument("--backend", default="mujoco", help="the physics backend of the main sweep")
    ap.add_argument("--max-time", type=float, default=MAX_TIME_S, help="simulated seconds allowed for one revolution")
    ap.add_argument("--no-k2", action="store_true", help="skip the K2 cross-check")
    ap.add_argument("--k2-scales", default=",".join(f"{s:g}" for s in K2_SCALES),
                    help="comma separated scale factors L of the K2 cross-check")
    ap.add_argument("--probe-cells", default=";".join(f"{s:g}:{p:g}:{f:g}" for s, p, f in PROBE_CELLS),
                    help="extra cells as scale:mass_exponent:joint_friction (the 'does not start' probes)")
    args = ap.parse_args(argv)

    scales = tuple(float(x) for x in args.scales.split(",") if x.strip())
    mass_exponents = tuple(float(x) for x in args.mass_exponents.split(",") if x.strip())
    friction_scales = tuple(float(x) for x in args.friction_scales.split(",") if x.strip())
    frictions = tuple(float(x) for x in args.frictions.split(",") if x.strip())
    k2_scales = () if args.no_k2 else tuple(float(x) for x in args.k2_scales.split(",") if x.strip())
    probe_cells = tuple(
        (float(a), float(b), float(c)) for a, b, c in (x.split(":") for x in args.probe_cells.split(";") if x.strip())
    )

    jobs = build_jobs(scales, mass_exponents, friction_scales, frictions, args.backend, k2_scales, args.max_time, probe_cells)

    # resume: a cell that is already in the output file is not simulated again
    old_cells: list[dict[str, Any]] = []
    old_timing: dict[str, Any] = {}
    old_protocol: dict[str, Any] = {}
    if os.path.exists(args.out):
        try:
            old_doc = json.load(open(args.out))
            old_cells = old_doc.get("cells", [])
            old_timing = old_doc.get("timing", {})
            old_protocol = old_doc.get("protocol", {})
        except (OSError, ValueError):
            old_cells = []
    done = {c["key"] for c in old_cells}
    # an alias cell is not simulated: it copies the numbers of the cell it points at
    todo = [j for j in jobs if j["key"] not in done and not j.get("alias_of")]
    print(f"{len(jobs)} cells in the protocol, {len(done)} already done, {len(todo)} to run on {args.workers} workers", flush=True)

    t_start = time.time()
    new_cells: list[dict[str, Any]] = []
    if todo:
        with make_executor(args.workers) as ex:
            for cell in ex.map(run_cell, todo):
                new_cells.append(cell)
                write_out(args.out, old_cells, new_cells, jobs, args, t_start, old_timing, old_protocol)

    cells = resolve_aliases(merge_cells(old_cells, new_cells), jobs)
    write_out(args.out, cells, [], jobs, args, t_start, old_timing, old_protocol)

    print("\n=== start wind vs scale (W-05) ===")
    print(f"{'L':>6} {'p':>4} {'jf (N*m)':>9} {'backend':>8} {'interval (lo, hi] m/s':>26} {'estimate':>9} {'sims':>5}")
    for c in sorted(cells, key=lambda c: (c["backend"], c["scale"], c["mass_exponent"], c["joint_friction_nm"])):
        hi = "inf" if math.isinf(c["hi_m_s"]) else f"{c['hi_m_s']:.4g}"
        est = "n/a" if not c["found"] else f"{c['estimate_m_s']:.4g}"
        print(f"{c['scale']:>6g} {c['mass_exponent']:>4g} {c['joint_friction_nm']:>9g} {c['backend']:>8} "
              f"{'(' + format(c['lo_m_s'], '.4g') + ', ' + hi + ']':>26} {est:>9} {c['simulations']:>5}")

    summ = summarise(cells)
    print("\nmeasured vs predicted log-log slopes (v vs L, friction 0, MuJoCo)")
    print(f"{'p':>4} {'measured':>10} {'predicted (lift)':>17} {'predicted (pin friction, weight)':>32} {'predicted (pin friction, as coded)':>34}")
    for k, v in summ["slopes"].items():
        print(f"{k:>4} {v['measured']:>10.3f} {v['predicted_lift']:>17.3f} {v['predicted_pin_friction_weight']:>32.3f} {v['predicted_pin_friction_absolute']:>34.3f}")
    if summ["does_not_start"]:
        print("\ncells that do not start (hi = inf):")
        for d in summ["does_not_start"]:
            print(f"  {d['key']}: highest wind tried {d['max_wind_tried_m_s']:g} m/s, {d['simulations']} simulations, {d['note']}")
    print(f"\nwall time {(time.time() - t_start) / 60:.1f} min -> {args.out}")


def write_out(path: str, cells: list[dict[str, Any]], new_cells: list[dict[str, Any]], jobs, args, t_start: float,
              old_timing: dict[str, Any] | None = None, old_protocol: dict[str, Any] | None = None) -> None:
    """Write the result file (after every finished cell, so a partial run is still usable)."""
    all_cells = merge_cells(cells, new_cells)
    per_cell = dict((old_timing or {}).get("per_cell_wall_time_s", {}))
    per_cell.update({c["key"]: c.get("_wall_time_s") for c in all_cells if c.get("_wall_time_s") is not None})
    timing = {
        "wall_time_s": time.time() - t_start,
        "total_cell_wall_time_s": sum(per_cell.values()),
        "per_cell_wall_time_s": per_cell,
    }
    # the protocol accumulates over the invocations of a resumed sweep: each invocation may carry a different
    # (smaller or larger) list of scales, and the file must show everything that was actually run
    prev = old_protocol or {}

    def union(key: str, values: list[Any]) -> list[Any]:
        out = list(prev.get(key, []))
        for v in values:
            if v not in out:
                out.append(v)
        return out
    doc = {
        "experiment": "W-05: the start wind as a function of the geometric scale factor",
        "evidence_level": "E0 (model against model; the K2 cross-check is the only independent element)",
        "design": f"schemas/examples/{DESIGN_NAME}",
        "definition": (
            "start wind = the lowest constant wind speed (m/s) at which the crank completes one full revolution within "
            f"{args.max_time:g} s from rest; bracket by doubling plus geometric bisection to 5 %; the result is the "
            "interval (lo, hi] (docs/EXPERIMENTS.md section 28)"
        ),
        "search": {"max_time_s": args.max_time, "give_up_after_s": 10.0, "rel_tol": 0.05, "w_max_m_s": 30.0, "w_min_m_s": 0.02},
        "scaling_rules": {
            "lengths": "unit, body_length, lateral_spacing, foot_radius x L",
            "masses": "body_mass x L**p; tube_mass_per_m x L**(p-1) so that a bar's mass is L**p; min_bar_mass x L**p",
            "sail": "sail_area x L**2; sail_radius x L; sail_gear unchanged (dimensionless)",
            "servo": "kp, kv, max_torque x L**(p+1) (they hold the weight during settle)",
            "not_scaled": "crank_friction 0.002 N*m, crank_damping 0.001 N*m*s/rad, rotor_inertia 1e-4 kg*m^2 (absolute defaults); "
            "joint_friction and joint_damping default 0 (ideal); body_drag_area 0",
            "manufacturing": "bar_width_mm / bar_thickness_mm only feed Design.bar_mass_per_m(); tube_mass_per_m is overridden, "
            "so the printed cross-section does not set the mass (it still sets the visual bar radius)",
        },
        "prediction": {
            "formula": "v(L) = A * L**((p-2)/2) + B * L, with A = v_ref - B and B = (2*pi/T) * gear * sail_radius",
            "v_ref_m_s": V_REF_M_S,
            "v_ref_source": "EXPERIMENTS.md section 28 (W-03): the unscaled walker needs (0.479, 0.500] m/s",
            "load_models": {
                "lift": "the load torque (raising the machine) is L**(p+1): slope (p-2)/2",
                "pin_friction_weight": "WIND.md section 4 premise (friction ~ normal force ~ weight): also L**(p+1): slope (p-2)/2",
                "pin_friction_absolute": "as coded (absolute Coulomb torque per pin): L**0: slope -1.5 "
                                         "(sign corrected on 2026-10-21; the pre-registration wrote +1.5)",
                "time_criterion": "the 40 s criterion adds omega_req*gear*r ~ L: slope 1",
            },
        },
        "protocol": {
            "scales": union("scales", [j["scale"] for j in jobs if j["backend"] == args.backend and j["joint_friction"] == 0.0]),
            "mass_exponents": union("mass_exponents", sorted({j["mass_exponent"] for j in jobs})),
            "friction_scales": union("friction_scales", [j["scale"] for j in jobs if j["joint_friction"] != 0.0]),
            "frictions": union("frictions", [j["joint_friction"] for j in jobs if j["joint_friction"] != 0.0]),
            "k2_scales": union("k2_scales", [j["scale"] for j in jobs if j["backend"] == "k2"]),
            "probe_cells": union("probe_cells", [x for x in args.probe_cells.split(";") if x.strip()]),
            "backend": args.backend,
            "workers": args.workers,
            "rel_tol": 0.05,
        },
        "cells": [{k: v for k, v in c.items() if not k.startswith("_")} for c in sorted(all_cells, key=lambda c: c["key"])],
        "summary": summarise(all_cells),
        "timing": timing,
    }
    with open(path, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=False)


if __name__ == "__main__":
    main()
