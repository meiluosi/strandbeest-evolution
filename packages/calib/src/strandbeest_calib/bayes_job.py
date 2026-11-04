"""Bayesian calibration of a Design against a Measurement: the emulator built from simulator runs, the posterior and the
identifiability verdict, returned as a Profile document with an `uncertainty` section."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
from strandbeest_common import Design
from strandbeest_common.ids import new_ulid
from strandbeest_common.schemas import validate
from strandbeest_sim import run

from .bayes import LogParam, build_emulator, infer, noise_from_data
from .calibrate import apply_parameters, parameter_registry, profile_source
from .conditions import measurement_scenario
from .compare import curves


def log_params(design: Design) -> dict[str, LogParam]:
    return {name: LogParam(name, p.lo, p.hi, p.apply)
            for name, p in parameter_registry(design).items() if p.supported}


def calibrate_bayes(design: Design, measurement: dict[str, Any], names: list[str], points: int = 32, progress: Callable[[int, int, str], None] | None = None) -> dict[str, Any]:
    avail = log_params(design)
    validate("measurement", measurement)
    if measurement["design_id"] != design.id:
        raise ValueError("Measurement design_id does not match the calibration Design")
    if not names or len(set(names)) != len(names):
        raise ValueError("calibration needs distinct supported parameters")
    unknown = [n for n in names if n not in avail]
    if unknown:
        raise ValueError(f"unknown parameters {unknown}; available: {sorted(avail)}")
    params = [avail[n] for n in names]
    ch = measurement["channels"]
    if "psi" not in ch or "torque" not in ch:
        raise ValueError("the measurement needs psi and torque channels")
    t, psi, tq = np.array(ch["t"]), np.array(ch["psi"]), np.array(ch["torque"])
    measured = curves(t, psi, tq, np.array(ch["x"]) if "x" in ch else None, 0.5)
    sigma = noise_from_data(t, psi, tq)

    base = measurement_scenario(design, measurement, {"revolutions": 2.2, "settle": 0.4, "frame_rate": 0})
    apply_parameters(design, base, {name: float(np.sqrt(avail[name].lo * avail[name].hi)) for name in names})

    def simulate(vals: dict[str, float]):
        res = run(apply_parameters(design, base, vals))
        return curves(res.t, res.psi, res.torque, res.x, 0.5)

    emu = build_emulator(params, simulate, points, seed=1, progress=(lambda i, k: progress(i, k, "emulator")) if progress else None)
    post = infer(emu, measured, sigma)
    summary = post.summary()
    profile = {
        "schema_version": 2,
        "id": new_ulid(),
        "name": f"{design.name}-bayes",
        "parameters": {n: summary[n]["best"] for n in names},
        "scenario": base.model_dump(mode="json", exclude_unset=True),
        "uncertainty": {n: {"ci95": summary[n]["posterior_ci95"], "profile_ci95": summary[n]["profile_ci95"], "identifiable": summary[n]["identifiable"],
                            "profile_share_of_prior": summary[n]["profile_share_of_prior"]} for n in names},
        "provenance": {
            **profile_source(design),
            "measurement_ids": [measurement["id"]],
            "synthetic": bool(measurement["synthetic"]),
            "method": f"Bayesian: RBF emulator from {points} simulator runs, Metropolis posterior, profile likelihood; emulator leave-one-out error {float(emu.sigma_emu.mean()):.3g}",
            "residual": post.chi2_min,
        },
    }
    validate("profile", profile)
    return profile
