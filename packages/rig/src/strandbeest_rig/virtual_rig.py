"""A virtual test rig: turn a simulator run into the raw CSV the real firmware would print, so the whole software chain
(logging -> conversion -> Measurement -> comparison -> calibration) can be exercised without hardware.

It is a test fixture, not evidence: the 'measurement' it makes comes from the same model it is later compared with."""

from __future__ import annotations

import io
import math

import numpy as np

from strandbeest_common import Design

from .calibration import Calibration


def virtual_raw_csv(
    design: Design,
    cal: Calibration,
    *,
    revolutions: float = 3.0,
    omega: float = 2.0,
    rate_hz: float = 100.0,
    current_noise_ma: float = 3.0,
    seed: int = 0,
    sim_overrides: dict | None = None,
) -> tuple[str, tuple[np.ndarray, np.ndarray]]:
    """Return (raw CSV text, (t, x) 'video tracking' arrays) for a simulated walk."""
    from strandbeest_sim import run, scenario_from_design

    ov = {"drive": {"omega": omega}, "run": {"revolutions": revolutions, "settle": 0.5}}
    for k, v in (sim_overrides or {}).items():
        ov.setdefault(k, {}).update(v) if isinstance(v, dict) else ov.__setitem__(k, v)
    res = run(scenario_from_design(design, ov))
    t_end = float(res.t[-1])
    t = np.arange(0.0, t_end, 1.0 / rate_hz)
    psi = np.interp(t, res.t, res.psi)
    torque = np.interp(t, res.t, res.torque)
    x = np.interp(t, res.t, res.x)
    rng = np.random.default_rng(seed)
    counts = np.round(cal.direction * psi / (2 * math.pi) * cal.gear_ratio * cal.counts_per_motor_rev).astype(int)
    current = cal.idle_current_ma + torque / cal.kt_nm_per_a * 1000.0 + rng.normal(0.0, current_noise_ma, len(t))
    out = io.StringIO()
    out.write("# fw=virtual-0.1 source=simulator\n# virtual rig: generated from a simulator run, not measured\n")
    out.write("t_ms,enc,current_mA,load_raw,wind_pulses,pwm\n")
    for i in range(len(t)):
        out.write(f"{int(round(t[i] * 1000))},{counts[i]},{current[i]:.1f},,,\n")
    return out.getvalue(), (t, x - x[0])
