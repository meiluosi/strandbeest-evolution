#!/usr/bin/env python3
"""Ranking Stability Study across Physics Backends, Friction Models, and Kinematic Metrics (V-04).

Evaluates whether design rankings remain stable across:
  1. Solvers: K2 (Moreau impulse + Coulomb dry stick-slip) vs MuJoCo (regularized soft contact)
  2. Ground Friction: Nominal (mu=1.5) vs Low (mu=0.5) vs High (mu=2.5)
  3. Dynamic Walking vs Pure Kinematic Fitness (flat stroke duty)
  4. Dynamic Walking vs Start Wind Speed (virtual dynamometer peak torque threshold)

Outputs Spearman rank correlation matrix and Top-5 overlap to verify acceptance criteria for V-04.
"""

from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

# Add repo packages to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "common" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "sim" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "opt" / "src"))

from strandbeest_common import Design
from strandbeest_opt.stability import evaluate_stability_suite
from strandbeest_sim.contract import _example_design

# 12 diverse, kinematically valid candidate designs
PARAM_VARIANTS = [
    ("D00_baseline", {}),
    ("D01_long_stroke", {"h": 68.0, "i": 51.0}),
    ("D02_high_lift", {"e": 58.0, "d": 42.0}),
    ("D03_crank_15_8", {"m": 15.8}),
    ("D04_crank_13_0", {"m": 13.0}),
    ("D05_wide_hip", {"a": 39.5}),
    ("D06_narrow_hip", {"a": 37.2}),
    ("D07_high_crank", {"l": 9.0}),
    ("D08_deep_foot", {"h": 68.0, "g": 38.0}),
    ("D09_compact", {"c": 37.5, "k": 60.0}),
    ("D10_stretched", {"b": 42.5, "j": 51.0}),
    ("D11_asym", {"c": 40.5, "f": 40.5}),
]


def build_candidate_designs() -> list[dict]:
    base = _example_design()
    designs = []
    for name, overrides in PARAM_VARIANTS:
        d = copy.deepcopy(base)
        d["name"] = name
        d["linkage"]["params"].update(overrides)
        designs.append(d)
    return designs


def main() -> None:
    print(f"=== Starting V-04 Ranking Stability Study (12 Candidate Designs) ===")
    t0 = time.time()
    designs = build_candidate_designs()
    print(f"Prepared {len(designs)} diverse candidate designs.")

    conditions = {
        "K2_Nominal": {
            "backend": "k2",
            "metric": "stride_per_rev",
            "overrides": {"terrain": {"friction": 1.5}},
        },
        "MuJoCo_Nominal": {
            "backend": "mujoco",
            "metric": "stride_per_rev",
            "overrides": {"terrain": {"friction": 1.5}},
        },
        "K2_Low_Friction": {
            "backend": "k2",
            "metric": "stride_per_rev",
            "overrides": {"terrain": {"friction": 0.5}},
        },
        "K2_High_Friction": {
            "backend": "k2",
            "metric": "stride_per_rev",
            "overrides": {"terrain": {"friction": 2.5}},
        },
        "Kinematic_Stroke": {
            "backend": "kinematic",
            "metric": "stroke_length",
        },
        "Kinematic_Duty": {
            "backend": "kinematic",
            "metric": "kinematic_flat_stroke",
        },
        "Start_Wind_Speed": {
            "metric": "start_wind",
        },
    }

    print("Evaluating conditions across all designs...")
    report = evaluate_stability_suite(designs, conditions, k=5)
    t_elapsed = time.time() - t0
    print(f"Completed evaluation in {t_elapsed:.1f} seconds.\n")

    print(report.summary_table())

    # Save results to experiments/ranking_stability_v04.json
    out_path = ROOT / "experiments" / "ranking_stability_v04.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
    print(f"\nSaved raw data to {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
