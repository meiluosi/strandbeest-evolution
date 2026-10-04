"""Compare a Measurement with a simulation Result on the quantities both have: crank torque vs angle, and stride."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

BINS = 36


@dataclass
class Curves:
    torque: np.ndarray  # mean torque per psi bin (NaN where no data), length BINS
    stride: float | None  # metres per crank revolution, if x is available


def curves(t: np.ndarray, psi: np.ndarray, torque: np.ndarray, x: np.ndarray | None = None, skip_rev: float = 0.0) -> Curves:
    """Bin torque by crank angle (mod 2π) after discarding the first `skip_rev` revolutions (start-up transient)."""
    psi = np.asarray(psi, float)
    mask = psi >= psi[0] + skip_rev * 2 * math.pi
    ang = np.mod(psi[mask] - psi[0], 2 * math.pi)
    idx = np.minimum((ang / (2 * math.pi) * BINS).astype(int), BINS - 1)
    tq = np.asarray(torque, float)[mask]
    mean = np.array([tq[idx == k].mean() if (idx == k).any() else np.nan for k in range(BINS)])
    stride = None
    if x is not None:
        xx = np.asarray(x, float)[mask]
        p = psi[mask]
        if p[-1] - p[0] > 1e-6:
            stride = float((xx[-1] - xx[0]) / (p[-1] - p[0]) * 2 * math.pi)
    return Curves(mean, stride)


def distance(a: Curves, b: Curves) -> float:
    """Dimensionless mismatch: RMS torque difference over mean |torque| of `a`, plus relative stride error when both exist."""
    ok = ~np.isnan(a.torque) & ~np.isnan(b.torque)
    if not ok.any():
        return float("inf")
    scale = max(float(np.nanmean(np.abs(a.torque))), 1e-12)
    d = float(np.sqrt(np.mean((a.torque[ok] - b.torque[ok]) ** 2)) / scale)
    if a.stride is not None and b.stride is not None and abs(a.stride) > 1e-9:
        d += abs(a.stride - b.stride) / abs(a.stride)
    return d
