"""Scenario schema. One document fully determines a run. Defaults marked 'assumption' are guesses, not measurements."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Linkage(_Strict):
    # "jansen", a path to a LinkageSpec JSON exported by packages/core, or an inline LinkageSpec object
    spec: Union[str, dict[str, Any]] = "jansen"
    # overrides of named lengths, e.g. {"m": 16.0}
    params: dict[str, float] = Field(default_factory=dict)


class Walker(_Strict):
    legs: int = Field(12, ge=1)
    mass: float = Field(50.0, gt=0, description="total mass, kg (torso gets what the bars do not); ignored if body_mass is set")
    body_mass: Union[float, None] = Field(None, gt=0, description="torso mass in kg; legs are added on top")
    unit: float = Field(0.02, gt=0, description="metres per length unit of the linkage (assumption)")
    direction: Literal[-1, 1] = -1  # crank turning sense that walks the leg forward; -1 for the Jansen leg
    tube_mass_per_m: float = Field(0.12, ge=0, description="kg per metre of tube (assumption)")
    min_bar_mass: float = Field(0.001, gt=0, description="floor on a bar's mass, kg")
    lateral_spacing: float = Field(0.1, ge=0, description="metres between neighbouring legs (visual only)")
    body_length: float = Field(1.0, gt=0, description="torso length, m: sets pitch inertia only (assumption)")
    pitch: Literal["free", "locked"] = Field("free", description="torso pitch freedom; 'locked' removes tipping")
    bar_radius: float = Field(0.008, gt=0, description="visual/collision-free capsule radius of bars, m")
    foot_radius: float = Field(0.01, gt=0)
    foot_friction: float = Field(1.5, gt=0)


class Terrain(_Strict):
    kind: str = "flat"
    friction: float = Field(1.5, gt=0)
    slope_deg: float = 0.0
    params: dict[str, Any] = Field(default_factory=dict)  # kind-specific


class Drive(_Strict):
    kind: str = "motor"
    omega: float = Field(0.3, description="crank speed in the walking direction, rad/s (motor drive)")
    kp: float = Field(5000.0, gt=0, description="position-servo stiffness, N·m per rad")
    kv: float = Field(500.0, gt=0, description="servo damping, N·m per rad/s")
    ramp: float = Field(2.0, ge=0, description="seconds to ramp up to omega")
    params: dict[str, Any] = Field(default_factory=dict)


class Solver(_Strict):
    timestep: float = Field(0.00025, gt=0, description="s; peak torque needs <= 0.25 ms to converge (docs/EXPERIMENTS.md section 8)")
    iterations: int = Field(100, ge=1)
    contact_solref: float = Field(0.02, gt=0, description="foot/terrain contact time constant, s; used only when contact_stiffness is unset. Depends on effective mass, so it is a numerical knob, not a physical one")
    contact_stiffness: Union[float, None] = Field(1e5, gt=0, description="foot pad stiffness, N/m (physical; a calibration target). Set to null to use contact_solref instead")
    contact_damping_ratio: float = Field(1.0, gt=0, description="damping ratio used to derive contact damping from the stiffness")
    cone: Literal["pyramidal", "elliptic"] = "pyramidal"
    impratio: float = Field(1.0, ge=1, description="friction-vs-normal constraint impedance ratio")
    noslip_iterations: int = Field(0, ge=0)
    solref_time: float = Field(0.002, gt=0, description="constraint stiffness time constant (smaller = stiffer; keep >= 2*timestep)")
    solimp: str = Field("0.99 0.999 0.0001", description="constraint impedance (MuJoCo solimp); near 1 = rigid joints")


class Run(_Strict):
    settle: float = Field(1.0, ge=0, description="seconds with the crank held before driving")
    revolutions: float = Field(3.0, gt=0)
    max_time: float = Field(600.0, gt=0)
    record_every: int = Field(10, ge=1)


class Scenario(_Strict):
    schema_version: int = SCHEMA_VERSION
    name: str = "unnamed"
    linkage: Linkage = Linkage()
    walker: Walker = Walker()
    terrain: Terrain = Terrain()
    drive: Drive = Drive()
    solver: Solver = Solver()
    run: Run = Run()


def load_scenario(source: Union[str, Path, dict]) -> Scenario:
    data = source if isinstance(source, dict) else yaml.safe_load(Path(source).read_text())
    return Scenario.model_validate(data)
