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
            "max_torque": 0.3,  # N·m, assumption: stall torque of a small geared motor; the motor stalls instead of forcing the legs open
        },
        # a softer constraint impedance: at this scale the stiffest setting (0.99 0.999) blew the loops apart
        "solver": {
            "timestep": 0.0002,
            "solref_time": 0.001,
            "solimp": "0.9 0.95 0.001",
            # Contact stiffness in MuJoCo's mass-normalised units (1/s^2), NOT N/m. A light walker on light legs needs a large
            # value: at 3e5 the feet sink about 0.6 mm (docs/EXPERIMENTS.md section 9). A calibration target.
            "contact_stiffness": 3e5,
        },
        "run": {"settle": 0.5, "revolutions": 1.5, "record_every": 10},
    }
    sail = d.get("sail") or {}
    if sail:
        sc["drive"].update(
            {k: sail[v] for k, v in (("sail_area", "area_m2"), ("sail_radius", "radius_m"), ("sail_drag_coeff", "drag_coeff"), ("sail_gear", "gear"),
                                      ("rotor_inertia", "inertia_kg_m2"), ("crank_damping", "damping_nm_s"), ("crank_friction", "friction_nm")) if v in sail}
        )
    if d.get("kind") == "sail":
        sc["drive"]["kind"] = "sail"
        sc["run"]["give_up_after"] = 8.0
        sc["run"]["max_time"] = 40.0
    for key, val in (overrides or {}).items():
        if isinstance(val, dict):
            sc.setdefault(key, {}).update(val)
        else:
            sc[key] = val
    return Scenario.model_validate(sc)
