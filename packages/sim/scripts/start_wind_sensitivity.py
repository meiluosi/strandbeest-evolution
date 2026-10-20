"""W-03: start wind of the small printed walker (sail drive, MuJoCo) and its sensitivity to every assumed parameter.

One-at-a-time: each assumption is moved to a low and a high value (a factor of 2 either way for the positive ones, small absolute
values for the pin losses whose default is zero), the start wind is searched again (bracket + geometric bisection, 5 % tolerance),
and the result is an interval, not a number. The baseline interval seeds the bracket of every other search.

Usage: python scripts/start_wind_sensitivity.py out.json [workers]
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design, sim_config
from strandbeest_sim.startwind import find_start_wind, simulate_attempt

# (name, section, field, low, high); None as the baseline means "read the default from the scenario"
PARAMS = [
    ("crank_friction", "drive", "crank_friction", 0.5, 2.0),
    ("crank_damping", "drive", "crank_damping", 0.5, 2.0),
    ("sail_drag_coeff", "drive", "sail_drag_coeff", 0.5, 2.0),
    ("sail_area", "drive", "sail_area", 0.5, 2.0),
    ("sail_gear", "drive", "sail_gear", 0.5, 2.0),
    ("foot_friction", "walker", "foot_friction", 0.5, 2.0),
    ("contact_stiffness", "solver", "contact_stiffness", 0.5, 2.0),
]
ABSOLUTE = [  # default 0 (ideal): absolute low/high values
    ("joint_friction", "walker", "joint_friction", 0.0005, 0.002),
    ("joint_damping", "walker", "joint_damping", 0.0002, 0.001),
]


def design() -> Design:
    return Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")


def search(job: tuple[str, dict, float]) -> dict:
    label, overrides, guess = job
    r = find_start_wind(simulate_attempt(design(), overrides), guess=guess, rel_tol=0.05)
    out = {"label": label, "overrides": overrides, **r.as_dict()}
    print(f"{label}: ({r.lo:.3g}, {r.hi:.3g}] m/s, {len(r.runs)} simulations{'' if r.trusted else ' [loops opened: not trusted]'} {r.note}", flush=True)
    return out


def main() -> None:
    out_path = sys.argv[1]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    sc = sim_config(scenario_from_design(design()))  # the flat configuration: the overrides below use its section names
    base = search(("baseline", {}, 0.5))
    guess = base["estimate"] if base["found"] else 0.5
    jobs: list[tuple[str, dict, float]] = []
    for name, sec, fld, lo, hi in PARAMS:
        default = getattr(getattr(sc, {"drive": "drive", "walker": "walker", "solver": "solver"}[sec]), fld)
        for tag, f in (("low", lo), ("high", hi)):
            jobs.append((f"{name} {tag}", {sec: {fld: default * f}}, guess))
    for name, sec, fld, lo, hi in ABSOLUTE:
        for tag, v in (("low", lo), ("high", hi)):
            jobs.append((f"{name} {tag}", {sec: {fld: v}}, guess))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(search, jobs))
    result = {"baseline": base, "rows": rows, "note": "start wind = lowest constant wind (m/s) at which the crank completes one revolution within 40 s; interval (lo, hi]"}
    json.dump(result, open(out_path, "w"), indent=2)
    print("\nparameter           low value -> interval          high value -> interval")
    for name, *_ in PARAMS + ABSOLUTE:
        lo_r = next(r for r in rows if r["label"] == f"{name} low")
        hi_r = next(r for r in rows if r["label"] == f"{name} high")
        print(f"{name:20s} ({lo_r['lo']:.3g}, {lo_r['hi']:.3g}]   ({hi_r['lo']:.3g}, {hi_r['hi']:.3g}]")
    if base["found"]:
        print(f"\nbaseline ({base['lo']:.3g}, {base['hi']:.3g}] m/s; sqrt-law check for sail parameters: x2 area -> {base['estimate'] / math.sqrt(2):.3g} m/s expected")


if __name__ == "__main__":
    main()
