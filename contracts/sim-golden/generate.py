#!/usr/bin/env python3
"""Record golden simulator runs: scenarios (flat schema-v1 form, which stays loadable through the v1 -> v2 migration) with the
metrics and a fingerprint of the time series they produced. tests assert that every later version of the simulator reproduces
them (same platform: to 1e-7 relative). Regenerate ONLY when a change of behaviour is intended and explained.

  python contracts/sim-golden/generate.py            # writes contracts/sim-golden/runs-contact-v3.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
from strandbeest_sim import load_scenario, run  # noqa: E402


def sample(a, n=24):
    a = np.asarray(a, float)
    idx = np.linspace(0, len(a) - 1, n).round().astype(int)
    return [float(a[i]) for i in idx]


def record(name, source_scenario):
    # Replay the exact previous inputs, including recorded defaults and sampling.
    # Rebuilding from today's defaults silently changes the comparison cohort.
    sc = load_scenario(source_scenario)
    res = run(sc)
    out = {
        "name": name,
        "scenario": source_scenario,
        "stalled": bool(res.stalled),
        "metrics": {k: (None if v != v else v if isinstance(v, bool) else float(v)) for k, v in res.metrics.items()},
        "samples": {"t": sample(res.t), "psi": sample(res.psi), "x": sample(res.x), "z": sample(res.z), "torque": sample(res.torque)},
        "n": int(len(res.t)),
    }
    if res.frames is not None:
        out["frames"] = {"count": int(len(res.frames["t"])), "bodies": int(res.frames["pos"].shape[1]), "contact_sum": int(res.frames["contact"].sum()),
                         "pos_sum": float(np.round(res.frames["pos"].astype(np.float64).sum(), 4))}
        out["scene"] = {"bodies": len(res.scene["bodies"]), "geoms": len(res.scene["geoms"]), "obstacles": len(res.scene["obstacles"])}
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).with_name("runs-energy-v2.json"))
    args = parser.parse_args()
    source = json.loads(args.source.read_text())
    runs = [record(row["name"], row["scenario"]) for row in source["runs"]]
    path = Path(__file__).with_name("runs-contact-v3.json")
    path.write_text(json.dumps({"_doc": "Golden simulator runs (platform: record machine; compare at rtol 1e-7). See generate.py.", "runs": runs}, indent=1) + "\n")
    for r in runs:
        print(f"{r['name']:<28} n={r['n']:>5} stalled={r['stalled']!s:<5} stride={r['metrics'].get('stride_per_rev')} peak_torque={r['metrics'].get('peak_torque')}")
