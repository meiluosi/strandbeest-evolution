import math

import numpy as np

from .registry import metrics


# Reproduces the window bias of 2026-10-05 (means over every sample, including the start-up and a partial last revolution).
# Kept ONLY so the simulator skeptic can prove it would catch it; never set it outside that test.
LEGACY_WINDOW = False


@metrics.register("gait")
def gait(res) -> dict:
    """Stride, speed and torque statistics over a whole number of crank revolutions.

    The first revolution (start-up ramp and transient) is skipped when the run has at least two; the window is then the largest
    whole number of revolutions after it, so a partial revolution never biases a mean. Runs shorter than two revolutions use
    everything and are flagged `steady_window: 0` (their means include the start-up)."""
    psi, x, t = res.psi, res.x, res.t
    rev = 2 * math.pi
    total_revs = (psi[-1] - psi[0]) / rev if len(psi) else 0.0
    if LEGACY_WINDOW:
        lo, hi, steady = psi[0], psi[-1], 1.0
    elif total_revs >= 1.98:  # a run asked to do 2 revolutions ends a hair short of 2.0
        n = max(1, math.floor(total_revs + 0.02) - 1)
        lo, hi, steady = rev, min(rev * (1 + n), psi[-1]), 1.0
    else:
        lo, hi, steady = 0.0, psi[-1] if len(psi) else 0.0, 0.0
    idx = np.flatnonzero((psi >= lo) & (psi <= hi))  # psi need not be monotonic if the crank is pushed back
    if len(idx) < 2 or psi[idx[-1]] - psi[idx[0]] <= 0:
        return {"stride_per_rev": float("nan"), "mean_speed": float("nan"), "steady_window": steady}
    i0, i1 = int(idx[0]), int(idx[-1])
    dpsi = psi[i1] - psi[i0]
    seg = res.torque[i0 : i1 + 1]
    return {
        "stride_per_rev": float((x[i1] - x[i0]) / dpsi * rev),
        "mean_speed": float((x[i1] - x[i0]) / (t[i1] - t[i0])),
        "mean_torque": float(np.mean(seg)),
        "peak_torque": float(np.max(seg)),
        "torque_ptp": float(np.ptp(seg)),
        "steady_window": steady,
    }


@metrics.register("energy")
def energy(res) -> dict:
    """Energy account over the same whole-revolution window as `gait`: input work per revolution and where it went.

    Per revolution the kinetic and potential energy are periodic, so in steady state (window >= 1 full revolution after the
    first) input = contact + loop + joint dissipation and the residual share should be near zero. Runs shorter than two
    revolutions use everything, include the start-up, and are flagged `steady_window: 0` by the gait metric; their residual is
    not a closure test."""
    s = getattr(res, "series", {}) or {}
    if not s or len(res.psi) < 2:
        return {}
    psi, rev = res.psi, 2 * math.pi
    total_revs = (psi[-1] - psi[0]) / rev
    if total_revs >= 1.98:
        n = max(1, math.floor(total_revs + 0.02) - 1)
        lo, hi = rev, min(rev * (1 + n), psi[-1])
    else:
        lo, hi = 0.0, psi[-1]
    idx = np.flatnonzero((psi >= lo) & (psi <= hi))
    if len(idx) < 2 or psi[idx[-1]] - psi[idx[0]] <= 0:
        return {}
    i0, i1 = int(idx[0]), int(idx[-1])
    revs = (psi[i1] - psi[i0]) / rev
    d = {k: float(s[k][i1] - s[k][i0]) for k in ("e_in", "e_contact", "e_loops", "e_friction")}
    d_mech = float((s["kinetic"][i1] + s["potential"][i1]) - (s["kinetic"][i0] + s["potential"][i0]))
    if d["e_in"] <= 1e-12:
        return {"energy_window_revs": float(revs)}
    return {
        "energy_in_per_rev": float(d["e_in"] / revs),
        "energy_contact_share": d["e_contact"] / d["e_in"],
        "energy_loops_share": d["e_loops"] / d["e_in"],
        "energy_friction_share": d["e_friction"] / d["e_in"],
        "energy_residual_share": (d["e_in"] - d["e_contact"] - d["e_loops"] - d["e_friction"] - d_mech) / d["e_in"],
        "energy_window_revs": float(revs),
    }
