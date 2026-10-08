#!/usr/bin/env python3
"""Record golden simulator runs: scenarios (flat schema-v1 form, which stays loadable through the v1 -> v2 migration) with the
metrics and a fingerprint of the time series they produced. tests assert that every later version of the simulator reproduces
them (same platform: to 1e-7 relative). Regenerate ONLY when a change of behaviour is intended and explained.

  python contracts/sim-golden/generate.py            # writes contracts/sim-golden/runs.json
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "schemas" / "examples" / "design-jansen-small-6leg.json"

from strandbeest_common import Design  # noqa: E402
from strandbeest_sim import run, scenario_from_design  # noqa: E402

FAST = {"run": {"revolutions": 0.7, "settle": 0.3, "frame_rate": 30}}
CASES = {
    "flat-motor": {},
    "slope-5deg": {"terrain": {"kind": "slope", "slope_deg": 5}},
    "step-12mm-torque-capped": {"terrain": {"kind": "step", "params": {"distance": 0.1, "height": 0.012}}},
    "bumps-seed3": {"terrain": {"kind": "bumps", "params": {"count": 8, "max_height": 0.01, "start": 0.1, "seed": 3}}},
    "soft-ground": {"terrain": {"kind": "soft", "params": {"stiffness": 4000.0, "damping": 120.0}}},
    "sail-wind-3": {"drive": {"kind": "sail"}, "wind": {"speed": 3.0}, "run": {"give_up_after": 8, "max_time": 40, "frame_rate": 0}},
    "sail-gusts": {"drive": {"kind": "sail"}, "wind": {"kind": "gusts", "speed": 2.5, "params": {"amplitude": 1.5, "period": 5}}, "run": {"give_up_after": 8, "max_time": 40, "frame_rate": 0}},
    "mars-gravity": {"environment": {"gravity": 3.73, "air_density": 0.02}},
    "four-legs-elliptic-cone": {"walker": {"legs": 4}, "solver": {"cone": "elliptic"}},
    "friction-impratio-10": {"solver": {"impratio": 10}},
}


def sample(a, n=24):
    a = np.asarray(a, float)
    idx = np.linspace(0, len(a) - 1, n).round().astype(int)
    return [float(a[i]) for i in idx]


def record(name, overrides):
    design = Design.load(DESIGN)
    ov = {"run": dict(FAST["run"])}
    for k, v in overrides.items():
        ov.setdefault(k, {}).update(v)
    sc = scenario_from_design(design, ov)
    res = run(sc)
    out = {
        "name": name,
        "scenario": json.loads(sc.model_dump_json()),
        "stalled": bool(res.stalled),
        "metrics": {k: (None if v != v else float(v)) for k, v in res.metrics.items()},
        "samples": {"t": sample(res.t), "psi": sample(res.psi), "x": sample(res.x), "z": sample(res.z), "torque": sample(res.torque)},
        "n": int(len(res.t)),
    }
    if res.frames is not None:
        out["frames"] = {"count": int(len(res.frames["t"])), "bodies": int(res.frames["pos"].shape[1]), "contact_sum": int(res.frames["contact"].sum()),
                         "pos_sum": float(np.round(res.frames["pos"].astype(np.float64).sum(), 4))}
        out["scene"] = {"bodies": len(res.scene["bodies"]), "geoms": len(res.scene["geoms"]), "obstacles": len(res.scene["obstacles"])}
    return out


if __name__ == "__main__":
    runs = [record(n, ov) for n, ov in CASES.items()]
    path = Path(__file__).with_name("runs.json")
    path.write_text(json.dumps({"_doc": "Golden simulator runs (platform: record machine; compare at rtol 1e-7). See generate.py.", "runs": runs}, indent=1) + "\n")
    for r in runs:
        print(f"{r['name']:<28} n={r['n']:>5} stalled={r['stalled']!s:<5} stride={r['metrics'].get('stride_per_rev')} peak_torque={r['metrics'].get('peak_torque')}")
