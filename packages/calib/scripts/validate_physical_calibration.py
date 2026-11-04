#!/usr/bin/env python3
"""Reproduce a short-window synthetic calibration study; never overwrite evidence.

Run using the installed repository packages, e.g.:
  .venv/bin/python packages/calib/scripts/validate_physical_calibration.py --output /tmp/calibration-study.json
This is model-internal diagnosis, not a physical build validation or a speed benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from strandbeest_calib.bayes import DigitalTwinModel, calibrate_digital_twin_bayes, simulate_digital_twin_trajectories
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new path to preserve previous results")
    document = json.loads((schema_dir() / "examples/design-jansen-small-6leg.json").read_text())
    document["walker"]["legs"] = 2
    design = Design(document)
    scenario = scenario_from_design(design, {"run": {"settle": .05, "max_time": .3, "revolutions": 2},
                                             "drive": {"omega": 4.0, "ramp": .03, "max_torque": .3}})
    times = np.linspace(0.0, .15, 16)
    cases = [
        ("pin-low-noise", {"pin_friction": .0015}, {"pin_friction": (.0004, .004)}, 1e-5, 8),
        ("pin-video-scale-noise", {"pin_friction": .0015}, {"pin_friction": (.0004, .004)}, .0008, 8),
        ("contact", {"contact_stiffness": 2e5}, {"contact_stiffness": (4e4, 8e5)}, 1e-5, 12),
        ("sand", {"sand_resistance": 2800}, {"sand_resistance": (1000, 5000)}, 1e-5, 12),
        ("friction", {"friction": 1.0}, {"friction": (.3, 3)}, 1e-5, 12),
        ("pin-contact", {"pin_friction": .0015, "contact_stiffness": 2e5},
         {"pin_friction": (.0004, .004), "contact_stiffness": (4e4, 8e5)}, 1e-5, 24),
    ]
    output = {"created_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "evidence": "synthetic model-internal; no measured device, video noise calibration, or physical validation",
              "design": document, "scenario": scenario.model_dump(mode="json", exclude_unset=True),
              "times_s": times.tolist(), "generation_seed": 42, "inference_seed": 123,
              "settings": {"n_samples": 500, "burn_in": 200, "validation_points": 4, "profile_grid": 15},
              "implementations": {}, "cases": []}

    def deduplicate_identities(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key == "implementation":
                    digest = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                    output["implementations"][digest] = item
                    result["implementation_ref_sha256"] = digest
                else:
                    result[key] = deduplicate_identities(item)
            return result
        if isinstance(value, list):
            return [deduplicate_identities(item) for item in value]
        return value

    # Exclusive creation protects earlier reports. A failed run remains explicitly incomplete.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump({**output, "complete": False}, handle, indent=2)
    for name, truth, priors, noise, points in cases:
        model = DigitalTwinModel(design, scenario)
        observations = simulate_digital_twin_trajectories(model, truth, times, noise_sigma=noise, seed=42)
        report = calibrate_digital_twin_bayes(model, observations.measurement, priors, seed=123,
                                             emulator_points=points, **output["settings"])
        row = {"case": name, "truth": truth, "priors": priors, "position_sigma_m": noise,
               "emulator_points": points, "report": deduplicate_identities(report.to_dict())}
        output["cases"].append(row)
        args.output.write_text(json.dumps({**output, "complete": False}, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"case": name, "map": report.map_estimate, "uncertainty": report.profile.uncertainty,
                          "native_calls": report.validation["native_calls"],
                          "emulator_holdout_sigma_rmse": report.validation["emulator_holdout_normalized_rmse"],
                          "native_time_holdout_sigma_rmse": report.validation["native_time_holdout_normalized_rmse"]}), flush=True)
    args.output.write_text(json.dumps({**output, "complete": True}, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
