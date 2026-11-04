"""Fit a few physically meaningful simulator parameters to a Measurement."""

from __future__ import annotations

import math
import copy
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from scipy.optimize import minimize

from strandbeest_common import Design, content_hash
from strandbeest_common.scenario import to_v2
from strandbeest_common.ids import new_ulid
from strandbeest_common.schemas import validate
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.config import Scenario, sim_config

from .compare import Curves, curves, distance
from .conditions import measurement_scenario, scenario_conditions

# v2 removes the old mass-dependent contact damping conversion. Fits made
# against that different forward model remain readable, but require refitting.
PARAMETER_MAPPING_VERSION = "beest-physical-v2"


@dataclass
class Param:
    name: str
    lo: float
    hi: float
    init: float
    # turn a value into scenario overrides, e.g. {"walker": {"foot_friction": v}, "terrain": {"friction": v}}
    apply: Callable[[float], dict[str, Any]]
    unit: str = "1"
    scenario_paths: tuple[str, ...] = ()
    supported: bool = True
    limitation: str = ""


FRICTION = Param("friction", 0.3, 3.0, 1.0,
                 lambda v: {"walker": {"foot_friction": v}, "terrain": {"friction": v}},
                 "1", ("entities[0].components.body.foot_friction", "world.terrain.friction"))
CONTACT_STIFFNESS = Param("contact_stiffness", 1e4, 1e7, 1e5,
                         lambda v: {"solver": {"contact_stiffness": v}},
                         "1/s^2", ("solver.contact_stiffness",))
PIN_FRICTION = Param("pin_friction", 1e-4, 0.01, 0.001,
                    lambda v: {"walker": {"joint_friction": v}},
                    "N*m", ("entities[0].components.body.joint_friction",))
# This is the actual backend's mass-normalised normal contact stiffness, not an RFT force coefficient.
# Damping stays an independent Scenario field; calibration must not silently couple it to stiffness.
SAND_RESISTANCE = Param("sand_resistance", 500.0, 20000.0, 2800.0,
                       lambda v: {"terrain": {"kind": "sand", "params": {"stiffness": v}}},
                       "1/s^2", ("world.terrain.params.stiffness",),
                       limitation="Equivalent compliant contact only; no granular flow or calibrated sand RFT.")


def _unsupported_flexibility(value: float) -> dict:
    raise ValueError("bar_flexibility is unsupported: the backend has rigid bars and no physical elastic DOF; walker.k_flex is not a Scenario field")


# Retained explicitly as an unmet capability, not silently removed or mapped to numerical loop softness.
BAR_FLEXIBILITY = Param("bar_flexibility", 1e-4, 0.05, 0.002, _unsupported_flexibility,
                        "m/N", (), supported=False,
                        limitation="Needs physical bar elasticity, energy accounting, and snapshot/restore validation.")
PARAMETERS = {p.name: p for p in (FRICTION, CONTACT_STIFFNESS, PIN_FRICTION, SAND_RESISTANCE, BAR_FLEXIBILITY)}


def parameter_registry(design: Design | None = None) -> dict[str, Param]:
    registry = dict(PARAMETERS)
    if design is not None:
        mass = design.bar_mass_per_m()
        registry["leg_mass_per_m"] = Param("leg_mass_per_m", 0.5 * mass, 2.0 * mass, mass,
            lambda v: {"walker": {"tube_mass_per_m": v}}, "kg/m", ("entities[0].components.body.tube_mass_per_m",))
    return registry


def parameter_overrides(values: dict[str, float], design: Design | None = None) -> dict[str, Any]:
    """The single registry for fitting and Profile application; unknown/unsupported fields fail before simulation."""
    if not isinstance(values, dict):
        raise TypeError("parameters must use registered names")
    registry = parameter_registry(design)
    overrides: dict[str, Any] = {}
    for name, value in values.items():
        if name not in registry:
            raise ValueError(f"unsupported calibration parameter {name!r}; legacy reduced-model mu_pin/alpha_sand/k_flex profiles have no automatic physical conversion")
        param = registry[name]
        if not param.supported:
            param.apply(value)  # raises the specific missing-physics explanation
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not param.lo <= value <= param.hi:
            raise ValueError(f"{name} must be finite in [{param.lo}, {param.hi}] {param.unit}")
        _merge(overrides, param.apply(float(value)))
    if "contact_stiffness" in values and "sand_resistance" in values:
        raise ValueError("contact_stiffness and sand_resistance target competing contact models; fit one at a time")
    return overrides


def apply_parameters(design: Design, scenario: Scenario | dict, parameters: dict[str, float]) -> Scenario:
    """Apply the same physical mappings during fitting and subsequent runs."""
    source = scenario if isinstance(scenario, Scenario) else Scenario.model_validate(scenario)
    cfg = sim_config(source).model_dump(mode="json")
    if cfg["linkage"]["spec"] != design.doc["linkage"] or cfg["linkage"]["params"]:
        raise ValueError("Scenario linkage must equal the supplied Design, without hidden parameter overrides")
    if cfg["walker"]["unit"] != design.walker["unit_m"]:
        raise ValueError("Scenario length scale must equal Design.walker.unit_m")
    overrides = parameter_overrides(parameters, design)
    terrain = overrides.get("terrain", {}).get("kind", cfg["terrain"]["kind"])
    if "contact_stiffness" in parameters and terrain in ("soft", "sand"):
        raise ValueError("contact_stiffness is overridden by soft/sand terrain; fit sand_resistance separately")
    if "sand_resistance" in parameters and cfg["terrain"]["kind"] == "slope" and cfg["terrain"]["slope_deg"]:
        raise ValueError("sand_resistance cannot preserve an incline in the current soft-ground backend")
    _merge(cfg, overrides)
    return Scenario.model_validate(to_v2(cfg))


def apply_profile(design: Design, profile: dict[str, Any], overrides: dict[str, Any] | None = None) -> Scenario:
    """Return an executable Scenario; never silently convert a legacy toy profile."""
    validate("profile", profile)
    prov = profile["provenance"]
    if prov.get("design_id") != design.id:
        raise ValueError("Profile design_id must match the forward Design")
    if prov.get("design_hash") != content_hash(design.doc, semantic_only=True):
        raise ValueError("Profile Design content differs from the current Design")
    if prov.get("parameter_mapping_version") != PARAMETER_MAPPING_VERSION or "scenario" not in profile:
        raise ValueError("Profile does not match the current physical parameter mapping; recalibrate instead of reusing a legacy forward model")
    cfg = sim_config(Scenario.model_validate(profile["scenario"])).model_dump(mode="json")
    _merge(cfg, copy.deepcopy(overrides or {}))
    return apply_parameters(design, Scenario.model_validate(to_v2(cfg)), profile["parameters"])


def profile_source(design: Design) -> dict[str, Any]:
    return {"design_id": design.id, "design_hash": content_hash(design.doc, semantic_only=True),
            "parameter_mapping_version": PARAMETER_MAPPING_VERSION}


def _merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict):
            _merge(dst.setdefault(k, {}), v)
        else:
            dst[k] = v
    return dst


def simulate_curves(design: Design, overrides: dict[str, Any], skip_rev: float = 0.5) -> tuple[Curves, Any]:
    res = run(scenario_from_design(design, overrides))
    return curves(res.t, res.psi, res.torque, res.x, skip_rev), res


def make_synthetic_measurement(
    design: Design, truth: dict[str, float], params: list[Param], noise: float = 0.03, seed: int = 0, name: str = "synthetic"
) -> dict[str, Any]:
    """A Measurement made by the simulator with known parameter values plus noise. Marked synthetic."""
    if set(truth) != {p.name for p in params}:
        raise ValueError("truth parameters must exactly match the requested registered parameters")
    ov = parameter_overrides(truth, design)
    scenario = scenario_from_design(design, ov)
    res = run(scenario)
    rng = np.random.default_rng(seed)
    tq = res.torque + rng.normal(0.0, noise * float(np.mean(np.abs(res.torque))), res.torque.shape)
    doc = {
        "schema_version": 2,
        "id": new_ulid(),
        "name": name,
        "design_id": design.id,
        "design_name": design.name,
        "synthetic": True,
        "build_note": f"simulator with {truth}, noise {noise}",
        "conditions": scenario_conditions(scenario),
        "channels": {"t": res.t.tolist(), "psi": res.psi.tolist(), "torque": tq.tolist(), "x": res.x.tolist()},
    }
    validate("measurement", doc)
    return doc


def calibrate(
    design: Design, measurement: dict[str, Any], params: list[Param], max_evals: int = 40, skip_rev: float = 0.5
) -> dict[str, Any]:
    """Nelder–Mead in log-parameter space, bounded by clipping. Returns a Profile document."""
    validate("measurement", measurement)
    ch = measurement["channels"]
    target = curves(np.array(ch["t"]), np.array(ch["psi"]), np.array(ch["torque"]), np.array(ch["x"]) if "x" in ch else None, skip_rev)
    if measurement["design_id"] != design.id:
        raise ValueError("Measurement design_id does not match the calibration Design")
    if not params or len({p.name for p in params}) != len(params) or max_evals < 1:
        raise ValueError("calibration needs distinct supported parameters and a positive evaluation budget")
    parameter_overrides({p.name: p.init for p in params}, design)
    base = measurement_scenario(design, measurement)
    apply_parameters(design, base, {p.name: p.init for p in params})
    log0 = np.log([p.init for p in params])
    history: list[tuple[list[float], float]] = []

    def values(z: np.ndarray) -> list[float]:
        return [float(np.clip(math.exp(zi), p.lo, p.hi)) for zi, p in zip(z, params)]

    def loss(z: np.ndarray) -> float:
        vals = values(z)
        scenario = apply_parameters(design, base, {p.name: value for p, value in zip(params, vals)})
        result = run(scenario)
        sim_c = curves(result.t, result.psi, result.torque, result.x, skip_rev)
        d = distance(target, sim_c)
        history.append((vals, d))
        return d if math.isfinite(d) else 1e6

    sol = minimize(loss, log0, method="Nelder-Mead", options={"maxfev": max_evals, "xatol": 0.02, "fatol": 1e-3, "initial_simplex": _simplex(log0)})
    best_vals, best_d = min(history, key=lambda h: h[1])
    profile = {
        "schema_version": 2,
        "id": new_ulid(),
        "name": f"{design.name}-calibrated",
        "parameters": {p.name: v for p, v in zip(params, best_vals)},
        "scenario": base.model_dump(mode="json", exclude_unset=True),
        "provenance": {
            **profile_source(design),
            "measurement_ids": [measurement["id"]],
            "synthetic": bool(measurement["synthetic"]),
            "method": f"Nelder-Mead on log-parameters, {len(history)} simulator runs",
            "residual": float(best_d),
        },
    }
    validate("profile", profile)
    return profile


def _simplex(z0: np.ndarray) -> np.ndarray:
    pts = [z0]
    for i in range(len(z0)):
        z = z0.copy()
        z[i] += 0.4
        pts.append(z)
    return np.array(pts)
