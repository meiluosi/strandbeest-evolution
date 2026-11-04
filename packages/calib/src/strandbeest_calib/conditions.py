"""Translate stated measurement conditions without silently fitting another experiment."""

from __future__ import annotations

import math

from strandbeest_common import Design
from strandbeest_common.schemas import validate
from strandbeest_sim import scenario_from_design
from strandbeest_sim.config import Scenario, sim_config


def _number(conditions: dict, key: str, default=None) -> float:
    value = conditions.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Measurement.conditions.{key} must be an explicit finite number")
    return float(value)


def measurement_scenario(design: Design, measurement: dict, run_options: dict | None = None) -> Scenario:
    """Phase-curve calibration supports stated motor speed or constant wind, on a rigid plane.

    Surface descriptions are retained as evidence, never guessed into material coefficients.
    The resulting Scenario records all remaining model assumptions explicitly.
    """
    validate("measurement", measurement)
    if measurement["design_id"] != design.id:
        raise ValueError("Measurement design_id does not match the calibration Design")
    conditions = measurement["conditions"]
    slope = _number(conditions, "slope_deg", 0.0)
    if abs(slope) >= 90:
        raise ValueError("calibration requires an incline strictly between -90 and 90 degrees")
    wind = _number(conditions, "wind_m_s", 0.0 if conditions["kind"] == "motor_no_wind" else None)
    if conditions["kind"] == "motor_no_wind":
        omega = _number(conditions, "omega_rad_s")
        if omega <= 0 or wind != 0:
            raise ValueError("motor_no_wind calibration requires positive crank speed and zero wind")
        drive = {"kind": "motor", "omega": omega}
    else:
        if design.doc["drive"]["kind"] != "sail":
            raise ValueError("fan calibration requires a sail Design; a motor-plus-fan experiment is not supported")
        drive = {"kind": "sail"}
    if any(not math.isclose(float(v), wind, abs_tol=1e-9, rel_tol=1e-9) for v in measurement["channels"].get("wind", [])):
        raise ValueError("varying measured wind requires an explicit time-dependent scenario; constant-wind calibration would discard it")
    overrides = {"drive": drive, "wind": {"kind": "constant", "speed": wind},
                 "terrain": {"kind": "slope" if slope else "flat", "slope_deg": slope}}
    if run_options:
        overrides["run"] = dict(run_options)
    return scenario_from_design(design, overrides)


def scenario_conditions(scenario: Scenario) -> dict:
    """State the actual conditions of a synthetic run, including wind-driven runs."""
    cfg = sim_config(scenario)
    conditions = {"kind": "motor_no_wind" if cfg.drive.kind == "motor" and cfg.wind.speed == 0 else "fan",
                  "wind_m_s": cfg.wind.speed,
                  "slope_deg": cfg.terrain.slope_deg if cfg.terrain.kind == "slope" else 0.0}
    if cfg.drive.kind == "motor":
        conditions["omega_rad_s"] = cfg.drive.omega
    return conditions


def validate_conditions(measurement: dict, scenario: Scenario) -> None:
    """The trajectory adapter has an explicit Scenario; reject conflicting metadata."""
    expected = scenario_conditions(scenario)
    actual = measurement["conditions"]
    if actual["kind"] != expected["kind"]:
        raise ValueError("Measurement conditions.kind conflicts with the forward Scenario")
    for key in ("omega_rad_s", "wind_m_s", "slope_deg"):
        if key in actual and key in expected:
            value = _number(actual, key)
            if not math.isclose(value, expected[key], rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"Measurement conditions.{key} conflicts with the forward Scenario")
