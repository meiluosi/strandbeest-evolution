"""Scale- and translation-invariant shape distance between foot loops: Python port of pathDistance in packages/core/src/metrics.ts."""

from __future__ import annotations

import numpy as np


def _normalise(path) -> np.ndarray:
    p = np.asarray(path, float)
    w = (p[:, 0].max() - p[:, 0].min()) or 1.0
    cx = (p[:, 0].max() + p[:, 0].min()) / 2
    cy = (p[:, 1].max() + p[:, 1].min()) / 2
    return np.column_stack(((p[:, 0] - cx) / w, (p[:, 1] - cy) / w))


def _mean_nearest(a: np.ndarray, b: np.ndarray) -> float:
    d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2))
    return float(d.min(axis=1).mean())


def path_distance(a, b) -> float:
    """0 = same shape (symmetric mean nearest-point distance in units of path width). Orientation is not normalised."""
    na, nb = _normalise(a), _normalise(b)
    return (_mean_nearest(na, nb) + _mean_nearest(nb, na)) / 2
