"""Fit a few physically meaningful simulator parameters to a Measurement."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from scipy.optimize import minimize

from strandbeest_common import Design
from strandbeest_common.schemas import validate
from strandbeest_sim import run, scenario_from_design

from .compare import Curves, curves, distance


@dataclass
class Param:
    name: str
    lo: float
    hi: float
    init: float
    # turn a value into scenario overrides, e.g. {"walker": {"foot_friction": v}, "terrain": {"friction": v}}
    apply: Callable[[float], dict[str, Any]]


FRICTION = Param("friction", 0.3, 3.0, 1.0, lambda v: {"walker": {"foot_friction": v}, "terrain": {"friction": v}})
CONTACT_STIFFNESS = Param("contact_stiffness", 300.0, 1e6, 3000.0, lambda v: {"solver": {"contact_stiffness": v}})


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
    design: Design, truth: dict[str, float], params: list[Param], noise: float = 0.03, seed: int = 0, mid: str = "synthetic"
) -> dict[str, Any]:
    """A Measurement made by the simulator with known parameter values plus noise. Marked synthetic."""
    ov: dict[str, Any] = {}
    for p in params:
        _merge(ov, p.apply(truth[p.name]))
    res = run(scenario_from_design(design, ov))
    rng = np.random.default_rng(seed)
    tq = res.torque + rng.normal(0.0, noise * float(np.mean(np.abs(res.torque))), res.torque.shape)
    doc = {
        "schema_version": 1,
        "id": mid,
        "design_name": design.name,
        "synthetic": True,
        "build_note": f"simulator with {truth}, noise {noise}",
        "conditions": {"kind": "motor_no_wind", "omega_rad_s": design.doc["drive"].get("motor_omega_rad_s", 2.0)},
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
    log0 = np.log([p.init for p in params])
    history: list[tuple[list[float], float]] = []

    def values(z: np.ndarray) -> list[float]:
        return [float(np.clip(math.exp(zi), p.lo, p.hi)) for zi, p in zip(z, params)]

    def loss(z: np.ndarray) -> float:
        vals = values(z)
        ov: dict[str, Any] = {}
        for p, v in zip(params, vals):
            _merge(ov, p.apply(v))
        sim_c, _ = simulate_curves(design, ov, skip_rev)
        d = distance(target, sim_c)
        history.append((vals, d))
        return d if math.isfinite(d) else 1e6

    sol = minimize(loss, log0, method="Nelder-Mead", options={"maxfev": max_evals, "xatol": 0.02, "fatol": 1e-3, "initial_simplex": _simplex(log0)})
    best_vals, best_d = min(history, key=lambda h: h[1])
    profile = {
        "schema_version": 1,
        "name": f"{design.name}-calibrated",
        "parameters": {p.name: v for p, v in zip(params, best_vals)},
        "provenance": {
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
