"""Video-observable trajectories from the same Design/Scenario/MuJoCo path used by normal runs.

This is an observation adapter, not an alternate dynamics model. It interpolates recorded
native positions and differentiates recorded crank angle; it never adds compliance/slip terms.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import numpy as np
from strandbeest_common import Design
from strandbeest_common.scenario import to_v2
from strandbeest_common.schemas import validate, schema_dir
from jsonschema import Draft202012Validator
from functools import lru_cache
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.config import Scenario, sim_config

from .calibrate import apply_parameters, apply_profile
from .identity import CALIBRATION_IMPLEMENTATION


@lru_cache(maxsize=1)
def _scenario_validator():
    return Draft202012Validator(json.loads((schema_dir()/"scenario.schema.json").read_text()))

def document_hash(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass
class DigitalTwinTrajectory:
    t: np.ndarray
    omega: np.ndarray
    foot_path: np.ndarray  # selected native foot centre minus native torso centre, world x/z, metres
    x_hip: np.ndarray  # world x displacement since driving started, metres
    crank_angle: np.ndarray  # walking direction, zero at start of driving
    torque: np.ndarray | None = None


class DigitalTwinModel:
    """A required explicit Design and its recorded physical scenario, with bounded observation sampling."""

    def __init__(self, design: Design, scenario: Scenario | dict | None = None, *, backend: str = "mujoco", foot_index: int = 0):
        if not isinstance(design, Design):
            raise TypeError("DigitalTwinModel requires an explicit Design document")
        if backend != "mujoco":
            raise ValueError("digital-twin parameter mappings are currently validated only for backend='mujoco'")
        self.design = Design(copy.deepcopy(design.doc))
        self.scenario = Scenario.model_validate(copy.deepcopy(scenario.model_dump(mode="json", exclude_unset=True) if isinstance(scenario, Scenario) else scenario)) if scenario is not None else scenario_from_design(self.design)
        cfg = sim_config(self.scenario)
        if cfg.linkage.spec != self.design.doc["linkage"] or cfg.linkage.params:
            raise ValueError("Scenario linkage must equal the supplied Design, without hidden parameter overrides")
        if cfg.walker.unit != self.design.walker["unit_m"]:
            raise ValueError("Scenario length scale must equal Design.walker.unit_m")
        if not isinstance(foot_index, int) or isinstance(foot_index, bool) or not 0 <= foot_index < cfg.walker.legs:
            raise ValueError("foot_index must select an existing foot in the Scenario")
        self.backend = backend
        self.foot_index = foot_index
        self.native_calls = 0
        self.native_seconds = 0.0
        self.last_native_scenario: dict | None = None
        self.native_runs: list[dict[str, Any]] = []

    @property
    def provenance(self) -> dict[str, Any]:
        doc = self.scenario.model_dump(mode="json", exclude_unset=True)
        return {"model": "PhysicsBackend observation adapter", "backend": self.backend, "backend_version": version("mujoco"),
                "design_id": self.design.id, "design_sha256": document_hash(self.design.doc), "scenario_sha256": document_hash(doc),
                "scenario": doc, "foot_index": self.foot_index,
                "coordinates": "selected foot centre minus torso centre in world x/z; SI metres",
                "time_origin": "start of driving after Scenario.run.settle", "omega_method": "gradient of recorded unwrapped crank angle",
                "implementation": CALIBRATION_IMPLEMENTATION.current()}

    def scenario_for(self, parameters: dict[str, float]) -> Scenario:
        result = apply_parameters(self.design, self.scenario, parameters)
        doc = result.model_dump(mode="json", exclude_unset=True)
        _scenario_validator().validate(doc)
        return result

    def apply_profile(self, profile: dict[str, Any]) -> Scenario:
        return apply_profile(self.design, profile)

    def predict(self, parameters: dict[str, float], t: np.ndarray) -> DigitalTwinTrajectory:
        if not isinstance(parameters, dict):
            raise TypeError("calibration parameters must use explicit registered names")
        t = np.asarray(t, dtype=float)
        if t.ndim != 1 or len(t) < 3 or not np.isfinite(t).all() or t[0] < 0 or not np.all(np.diff(t) > 0):
            raise ValueError("prediction times must be finite, increasing, nonnegative, and contain at least three samples")
        cfg = sim_config(self.scenario_for(parameters))
        dt = cfg.solver.timestep
        if np.min(np.diff(t)) < dt * (1-1e-9):
            raise ValueError("observation sampling cannot be finer than the Scenario timestep")
        if t[-1] > cfg.run.max_time:
            raise ValueError("requested observations exceed Scenario.run.max_time")
        # These change recording and the stop budget only, never physical solver/drive parameters.
        cfg.run.record_every = min(cfg.run.record_every, max(1, int(np.min(np.diff(t))/dt/2)))
        interval = cfg.run.record_every * dt
        cfg.run.frame_rate = 1.0 / interval
        cfg.run.max_time = min(cfg.run.max_time, float(t[-1]) + interval + 2*dt)
        self.last_native_scenario = to_v2(cfg.model_dump(mode="json"))
        record = {"parameters": dict(parameters), "scenario": copy.deepcopy(self.last_native_scenario),
                  "scenario_sha256": document_hash(self.last_native_scenario),
                  "design_sha256": document_hash(self.design.doc), "backend": self.backend,
                  "backend_version": version("mujoco"), "implementation": CALIBRATION_IMPLEMENTATION.current(),
                  "completed": False}
        started = time.perf_counter()
        try:
            result = run(Scenario.model_validate(self.last_native_scenario), backend=self.backend)
            record["completed"] = True
        finally:
            self.native_seconds += time.perf_counter() - started
            self.native_calls += 1
            record["implementation_unchanged"] = record["implementation"] == CALIBRATION_IMPLEMENTATION.current()
            self.native_runs.append(record)
        frames = result.frames
        if frames is None or not result.scene or len(result.t) < 3:
            raise ValueError("native run did not record enough trajectory data")
        ft = np.asarray(frames["t"], dtype=float)
        if t[0] < max(float(result.t[0]), float(ft[0])) - 1e-9 or t[-1] > min(float(result.t[-1]), float(ft[-1])) + 1e-9:
            raise ValueError("native run ended before the requested observations; no extrapolation is performed")
        torso_index = result.scene["bodies"].index("torso")
        torso = np.asarray(frames["pos"][:, torso_index, :], dtype=float)
        foot = np.asarray(frames["foot_pos"][:, self.foot_index, :], dtype=float)
        relative = foot - torso
        return DigitalTwinTrajectory(
            t=t.copy(),
            omega=np.interp(t, result.t, np.gradient(result.psi, result.t, edge_order=2)),
            foot_path=np.column_stack([np.interp(t, ft, relative[:, 0]), np.interp(t, ft, relative[:, 2])]),
            x_hip=np.interp(t, result.t, result.x)-result.x[0],
            crank_angle=np.interp(t, result.t, result.psi),
            torque=np.interp(t, result.t, result.torque),
        )
