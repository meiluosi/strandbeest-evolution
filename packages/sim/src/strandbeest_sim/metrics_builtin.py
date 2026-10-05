import math

import numpy as np

from .registry import metrics


@metrics.register("gait")
def gait(res) -> dict:
    """Stride, speed and torque statistics over a whole number of crank revolutions.

    The first revolution (start-up ramp and transient) is skipped when the run has at least two; the window is then the largest
    whole number of revolutions after it, so a partial revolution never biases a mean. Runs shorter than two revolutions use
    everything and are flagged `steady_window: 0` (their means include the start-up)."""
    psi, x, t = res.psi, res.x, res.t
    rev = 2 * math.pi
    total_revs = (psi[-1] - psi[0]) / rev if len(psi) else 0.0
    if total_revs >= 1.98:  # a run asked to do 2 revolutions ends a hair short of 2.0
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
