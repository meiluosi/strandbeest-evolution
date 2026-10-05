"""Rig calibration: the constants that turn raw counts into crank angle, torque and wind speed."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Union

import numpy as np

G = 9.80665


@dataclass
class Calibration:
    # encoder on the motor shaft
    counts_per_motor_rev: float = 48.0  # quadrature counts per motor-shaft revolution (assumption: set from the datasheet, then check by hand)
    gear_ratio: float = 100.0  # motor revolutions per crank revolution
    direction: int = 1  # +1 if positive counts mean the crank turns in the walking direction
    # torque, by one of two methods
    torque_method: Literal["current", "load_cell"] = "current"
    kt_nm_per_a: float = 0.5  # crank torque per amp, INCLUDING gearbox efficiency; calibrate with `torque-cal`
    idle_current_ma: float = 0.0  # current with the crank free and no legs attached (removes motor + gearbox friction)
    arm_m: float = 0.05  # load-cell lever arm (load_cell method)
    counts_per_gram: float = 1.0  # load-cell scale (load_cell method)
    zero_counts: float = 0.0
    # wind
    wind_ms_per_hz: float = 0.0  # anemometer: wind speed (m/s) per pulse frequency (Hz); 0 = no anemometer
    calibrated: bool = False  # set true only after you checked the constants against your own rig
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, source: Union[str, Path, dict]) -> "Calibration":
        d = source if isinstance(source, dict) else json.loads(Path(source).read_text())
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "extra"}
        c = cls(**known)
        c.extra = {k: v for k, v in d.items() if k not in cls.__dataclass_fields__}
        return c

    def asdict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(d.pop("extra"))
        return d


@dataclass
class TorqueFit:
    kt_nm_per_a: float
    idle_current_ma: float
    residual_nm: float  # RMS torque error of the straight-line fit
    n: int


def fit_torque_from_hanging_masses(masses_g: list[float], currents_ma: list[float], arm_m: float) -> TorqueFit:
    """Static calibration. Hang known masses on a lever arm of length `arm_m` fixed to the crank shaft, hold the crank still
    against the load, and record the motor current for each mass. Torque is m*g*arm; fit torque = Kt * (I - I0)."""
    if len(masses_g) != len(currents_ma) or len(masses_g) < 3:
        raise ValueError("need at least 3 (mass, current) points of the same length")
    torque = np.array(masses_g) * 1e-3 * G * arm_m
    amps = np.array(currents_ma) * 1e-3
    A = np.vstack([amps, np.ones_like(amps)]).T
    (kt, c), *_ = np.linalg.lstsq(A, torque, rcond=None)
    if kt <= 0:
        raise ValueError("fit gave a non-positive torque constant; check that current rises with the hanging mass")
    resid = float(np.sqrt(np.mean((A @ np.array([kt, c]) - torque) ** 2)))
    return TorqueFit(float(kt), float(-c / kt * 1e3), resid, len(masses_g))
