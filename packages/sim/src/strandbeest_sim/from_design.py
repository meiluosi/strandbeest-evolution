"""Build a simulator Scenario from a Design (the platform's single source of truth for a walker)."""

from __future__ import annotations

from typing import Any

from strandbeest_common import Design

from .config import Scenario


def scenario_from_design(design: Design, overrides: dict[str, Any] | None = None) -> Scenario:
    """Flat-ground, motor-driven scenario for `design`.

    Printed-bar mass comes from the cross-section and material (assumption-driven, see strandbeest_common.design).
    Servo gains scale with the walker so a 0.3 kg bench model is not driven by a 50 kg-class servo.
    """
    w, d, m = design.walker, design.doc["drive"], design.mfg
    unit = w["unit_m"]
    total = w["body_mass_kg"] + w["legs"] * 0.05  # rough, only used to scale the servo
    sc: dict[str, Any] = {
        "name": design.name,
        "linkage": {"spec": design.doc["linkage"]},
        "walker": {
            "legs": w["legs"],
            "body_mass": w["body_mass_kg"],
            "unit": unit,
            "direction": w["direction"],
            "tube_mass_per_m": design.bar_mass_per_m(),
            "min_bar_mass": 1e-4,
            "lateral_spacing": w.get("lateral_spacing_m", 0.014),
            "body_length": w.get("body_length_m", 0.25),
            "bar_radius": m["bar_width_mm"] / 2000.0,
            "foot_radius": max(m["bar_width_mm"] / 2000.0 * 0.4, 0.001),
            "pitch": "locked",
        },
        "drive": {
            "kind": "motor",
            "omega": d.get("motor_omega_rad_s", 2.0),
            "kp": 200.0 * total * 9.81 * unit * 10,
            "kv": 20.0 * total * 9.81 * unit * 10,
            "ramp": 1.0,
        },
        # a softer constraint impedance: at this scale the stiffest setting (0.99 0.999) blew the loops apart
        "solver": {
            "timestep": 0.0002,
            "solref_time": 0.001,
            "solimp": "0.9 0.95 0.001",
            # assumption: pad stiffness such that three feet carrying the weight sink 1 mm; a calibration target
            "contact_stiffness": max(total * 9.81 / (3 * 0.001), 500.0),
        },
        "run": {"settle": 0.5, "revolutions": 1.5, "record_every": 10},
    }
    for key, val in (overrides or {}).items():
        if isinstance(val, dict):
            sc.setdefault(key, {}).update(val)
        else:
            sc[key] = val
    return Scenario.model_validate(sc)
