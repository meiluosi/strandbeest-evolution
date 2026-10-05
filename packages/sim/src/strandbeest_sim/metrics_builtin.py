import math

import numpy as np

from .registry import metrics


@metrics.register("gait")
def gait(res) -> dict:
    """Stride per revolution and mean speed over the revolutions after the start-up ramp."""
    sc = res.scenario
    ramp_rev = 0.0
    psi, x, t = res.psi, res.x, res.t
    # skip the first revolution (ramp + transient) when there is more than one
    start = 2 * math.pi if psi[-1] > 2 * math.pi * 1.5 else 0.0
    reached = np.flatnonzero(psi >= start)  # psi need not be monotonic if the crank is pushed back
    i0 = int(reached[0]) if len(reached) else 0
    dpsi = psi[-1] - psi[i0]
    if dpsi <= 0:
        return {"stride": float("nan"), "mean_speed": float("nan")}
    stride = (x[-1] - x[i0]) / dpsi * 2 * math.pi
    speed = (x[-1] - x[i0]) / (t[-1] - t[i0])
    del ramp_rev, sc
    return {
        "stride_per_rev": float(stride),
        "mean_speed": float(speed),
        "mean_torque": float(np.mean(res.torque[i0:])),
        "peak_torque": float(np.max(res.torque[i0:])),
        "torque_ptp": float(np.ptp(res.torque[i0:])),
    }
