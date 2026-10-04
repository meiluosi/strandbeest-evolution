"""P1: separate numerical settings (should converge) from physical settings (should be set by measurement).

Usage: python scripts/p1_study.py out.json
Baseline: 12 legs, flat ground, 50 kg, tube 0.12 kg/m, crank 0.6 rad/s, 2.5 revolutions, foot stiffness 1e5 N/m, mu 1.5.
Each group changes one thing at a time. Metrics are taken after the first revolution.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor

BASE = {
    "walker": {"legs": 12, "pitch": "locked", "mass": 50, "tube_mass_per_m": 0.12},
    "drive": {"omega": 0.6, "ramp": 2},
    "run": {"revolutions": 2.5, "settle": 1.0, "record_every": 8},
    "solver": {"contact_stiffness": 1e5},
}

GROUPS = {
    "A1 timestep": [{"solver": {"timestep": dt}} for dt in (1e-3, 5e-4, 2.5e-4, 1.25e-4)],
    "A2 iterations": [{"solver": {"iterations": n}} for n in (30, 100, 300)],
    "A3 cone": [{"solver": {"cone": c}} for c in ("pyramidal", "elliptic")],
    "A4 impratio": [{"solver": {"impratio": r}} for r in (1, 10)],
    "A5 noslip": [{"solver": {"noslip_iterations": n}} for n in (0, 10)],
    "A6 loop stiffness": [{"solver": {"solref_time": t}} for t in (0.004, 0.002, 0.001)]
    + [{"solver": {"solimp": "0.9 0.95 0.001"}}, {"solver": {"solimp": "0.99 0.999 0.0001"}}],
    "B1 foot stiffness N/m": [{"solver": {"contact_stiffness": k}} for k in (1e4, 3e4, 1e5, 3e5, 1e6)],
    "B2 friction": [{"walker": {"foot_friction": m}, "terrain": {"friction": m}} for m in (0.5, 0.8, 1.2, 2.0, 3.0)],
    "B3 foot radius m": [{"walker": {"foot_radius": r}} for r in (0.005, 0.01, 0.02)],
    "B4 tube mass kg/m": [{"walker": {"tube_mass_per_m": m}} for m in (0.05, 0.12, 0.2)],
}


def merge(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if isinstance(v, dict):
            merge(a.setdefault(k, {}), v)
        else:
            a[k] = v
    return a


def job(args):
    group, change = args
    import math

    from strandbeest_sim import load_scenario, run

    cfg = merge(json.loads(json.dumps(BASE)), change)
    try:
        res = run(load_scenario(cfg))
        m = {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in res.metrics.items()}
        m["stalled"] = res.stalled
    except Exception as e:  # keep the sweep going, record the failure
        m = {"error": f"{type(e).__name__}: {e}"}
    return group, change, m


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "p1-study.json"
    tasks = [(g, c) for g, cs in GROUPS.items() for c in cs]
    with ProcessPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(job, tasks))
    doc: dict = {"base": BASE, "groups": {}}
    for g, c, m in results:
        doc["groups"].setdefault(g, []).append({"change": c, "metrics": m})
    json.dump(doc, open(out, "w"), indent=2)
    for g, rows in doc["groups"].items():
        print("==", g)
        for r in rows:
            m = r["metrics"]
            print("  ", json.dumps(r["change"]), "->", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items() if k in ("stride_per_rev", "mean_torque", "torque_ptp", "max_loop_violation", "error", "stalled")})


if __name__ == "__main__":
    main()
