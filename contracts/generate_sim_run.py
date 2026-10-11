"""Generate contracts/sim-run/cases.json: short Python runs (settle + a fraction of a revolution) with everything the browser
preview records, unrounded: the crank series, the replay frames (poses, foot contacts, loads, centre of mass), the replay scene
and the gait metrics. packages/sim-web runs the same scenarios on MuJoCo WebAssembly and must follow these to rounding.

Run from the repo root with the packages on the path:
  PYTHONPATH=packages/common/src:packages/sim/src ../strandbeest-evolution/.venv/bin/python contracts/generate_sim_run.py"""

import copy
import json
from pathlib import Path

import numpy as np

from strandbeest_common import Design
from strandbeest_sim import run, scenario_from_design

ROOT = Path(__file__).parents[1]
DESIGN = "schemas/examples/design-jansen-small-6leg.json"
OUT = ROOT / "contracts" / "sim-run" / "cases.json"

CASES = [
    ("flat", {"run": {"revolutions": 0.15, "frame_rate": 30}}),
    # a step the first swing feet reach: the contact list is not empty and a foot is blocked
    ("step", {"terrain": {"kind": "step", "params": {"distance": 0.03, "height": 0.006}}, "run": {"revolutions": 0.2, "frame_rate": 30}}),
    ("slope", {"terrain": {"kind": "slope", "slope_deg": 8.0}, "run": {"revolutions": 0.12, "frame_rate": 30}}),
    ("soft", {"terrain": {"kind": "soft", "params": {"stiffness": 5000.0, "damping": 90.0}}, "run": {"revolutions": 0.12, "frame_rate": 30}}),
]


def lists(a):
    return np.asarray(a, dtype=float).tolist()


def one(overrides):
    design = Design.load(ROOT / DESIGN)
    res = run(scenario_from_design(design, copy.deepcopy(overrides)))
    f = res.frames
    s = res.scene
    gait = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in res.metrics.items() if k in ("stride_per_rev", "mean_speed", "mean_torque", "peak_torque", "torque_ptp", "steady_window")}
    return {
        "series": {"t": lists(res.t), "psi": lists(res.psi), "x": lists(res.x), "torque": lists(res.torque)},
        "frames": {k: lists(f[k]) for k in ("t", "pos", "quat", "foot_pos", "foot_force", "foot_slip", "com")} | {"contact": np.asarray(f["contact"], dtype=int).tolist()},
        "scene": s,
        "metrics": gait,
        "stalled": bool(res.stalled),
    }


def main() -> None:
    cases = [{"name": n, "design": DESIGN, "overrides": ov, "expected": one(ov)} for n, ov in CASES]
    for c in cases:
        e = c["expected"]
        print(c["name"], len(e["series"]["t"]), "samples", len(e["frames"]["t"]), "frames", "feet down max", max(sum(x) for x in e["frames"]["contact"]))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"note": "Python runs for packages/sim-web/src/run.test.ts; regenerate with contracts/generate_sim_run.py", "cases": cases}, separators=(",", ":")) + "\n")
    print(OUT.stat().st_size // 1000, "kB")


if __name__ == "__main__":
    main()
