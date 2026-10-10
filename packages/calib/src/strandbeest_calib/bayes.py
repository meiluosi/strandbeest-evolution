"""Bayesian calibration with an emulator, and an identifiability check (O-04).

The simulator is too slow for MCMC (seconds per run), so we run it at K space-filling points of the parameter box, fit an
RBF emulator of what the data are made of (the torque curve in 36 crank-angle bins and the stride), and do inference on the
emulator:
  posterior   random-walk Metropolis over log-parameters with a uniform prior on the box; Gaussian likelihood on the
              torque bins and the stride, with the noise estimated from the data and the emulator's own leave-one-out error
              added in quadrature so an inaccurate emulator widens the posterior instead of faking precision
  profile     for every parameter, the best achievable fit as that parameter is held at each value of its range (the other
              parameters re-optimised); the 95 % interval is where the profile stays within 1.92 of its minimum (chi^2/2)
  verdict     a parameter is NOT identifiable when its profile interval covers more than 60 % of the log-range of the prior
              (the data cannot tell most of its values apart)
Everything here is model against model unless the measurement is real; a calibration on synthetic data only shows the
machinery works."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.optimize import minimize
import warnings

from scipy.stats import qmc

from .calibrate import Param, _merge
from .compare import BINS, Curves, curves


@dataclass
class LogParam:
    """A parameter explored in log space between lo and hi."""

    name: str
    lo: float
    hi: float
    apply: Callable[[float], dict[str, Any]]

    def value(self, u: float) -> float:  # u in [0, 1]
        return math.exp(math.log(self.lo) + u * (math.log(self.hi) - math.log(self.lo)))

    def unit(self, v: float) -> float:
        return (math.log(v) - math.log(self.lo)) / (math.log(self.hi) - math.log(self.lo))


def from_param(p: Param) -> LogParam:
    return LogParam(p.name, p.lo, p.hi, p.apply)


def features(c: Curves) -> np.ndarray:
    """What the likelihood compares: the 36 torque bins (NaN -> 0 weight handled by the caller) and the stride."""
    return np.concatenate([c.torque, [c.stride if c.stride is not None else np.nan]])


@dataclass
class Emulator:
    params: list[LogParam]
    points: np.ndarray  # (K, P) unit-cube coordinates
    y: np.ndarray  # (K, BINS + 1)
    sigma_emu: np.ndarray = field(default=None)  # leave-one-out RMS error per feature
    _rbf: RBFInterpolator = field(default=None, repr=False)

    def fit(self) -> "Emulator":
        y = np.where(np.isnan(self.y), np.nanmean(self.y, axis=0), self.y)
        self._y = y
        self._rbf = RBFInterpolator(self.points, y, kernel="thin_plate_spline", smoothing=1e-9, degree=1)
        # leave-one-out error (honest about how well the emulator interpolates between the runs)
        err = []
        for k in range(len(self.points)):
            keep = np.arange(len(self.points)) != k
            r = RBFInterpolator(self.points[keep], y[keep], kernel="thin_plate_spline", smoothing=1e-9, degree=1)
            err.append(r(self.points[k : k + 1])[0] - y[k])
        self.sigma_emu = np.sqrt(np.mean(np.square(err), axis=0))
        return self

    def __call__(self, u: np.ndarray) -> np.ndarray:
        return self._rbf(np.atleast_2d(u))


def build_emulator(params: list[LogParam], simulate: Callable[[dict[str, float]], Curves], k: int, seed: int = 0, progress: Callable[[int, int], None] | None = None) -> Emulator:
    """Run `simulate` (values by parameter name -> Curves) at k scrambled-Sobol points of the box."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pts = qmc.Sobol(d=len(params), scramble=True, seed=seed).random(k)  # k need not be a power of 2: fine for an emulator design
    ys = []
    for i, u in enumerate(pts):
        ys.append(features(simulate({p.name: p.value(float(x)) for p, x in zip(params, u)})))
        if progress:
            progress(i + 1, k)
    return Emulator(params, pts, np.array(ys)).fit()


def noise_from_data(t, psi, torque, skip_rev: float = 0.5, floor_share: float = 0.01) -> np.ndarray:
    """Standard error of each torque bin of the measurement: spread across revolutions when there are at least 3 of them, else
    the within-bin spread (which also contains the real variation inside a bin, so it is an over-estimate)."""
    psi = np.asarray(psi, float)
    tq = np.asarray(torque, float)
    keep = psi >= psi[0] + skip_rev * 2 * math.pi
    ang = psi[keep] - psi[0]
    tq = tq[keep]
    rev = (ang // (2 * math.pi)).astype(int)
    idx = np.minimum((np.mod(ang, 2 * math.pi) / (2 * math.pi) * BINS).astype(int), BINS - 1)
    revs = sorted(set(rev))
    full = [r for r in revs if (rev == r).sum() > BINS * 3]
    se = np.full(BINS, np.nan)
    if len(full) >= 3:
        per = np.array([[tq[(rev == r) & (idx == b)].mean() if ((rev == r) & (idx == b)).any() else np.nan for b in range(BINS)] for r in full])
        se = np.nanstd(per, axis=0, ddof=1) / math.sqrt(len(full))
    else:
        for b in range(BINS):
            sel = tq[idx == b]
            if len(sel) > 2:
                se[b] = sel.std(ddof=1) / math.sqrt(len(sel))
    floor = floor_share * float(np.nanmean(np.abs(tq)))  # no real instrument is better than this; it is an assumption
    return np.where(np.isnan(se), floor, np.maximum(se, floor))


@dataclass
class Posterior:
    params: list[LogParam]
    samples: np.ndarray  # (N, P) unit-cube
    profile_grid: np.ndarray  # (G,)
    profile: np.ndarray  # (P, G) minimum of 0.5*chi^2 with the parameter held fixed
    chi2_min: float
    best: np.ndarray  # unit-cube best fit

    def summary(self, identifiable_share: float = 0.6) -> dict[str, dict[str, Any]]:
        out = {}
        for i, p in enumerate(self.params):
            u = self.samples[:, i]
            vals = np.array([p.value(float(x)) for x in u])
            ok = self.profile[i] - self.profile[i].min() <= 1.92
            step = float(self.profile_grid[1] - self.profile_grid[0])
            lo_u = max(0.0, float(self.profile_grid[ok].min()) - step / 2)
            hi_u = min(1.0, float(self.profile_grid[ok].max()) + step / 2)  # a one-point interval is one grid cell wide
            share = float(hi_u - lo_u)  # share of the log-range of the prior that the data cannot exclude (95 %)
            out[p.name] = {
                "best": p.value(float(self.best[i])),
                "posterior_median": float(np.median(vals)),
                "posterior_ci95": [float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))],
                "profile_ci95": [p.value(float(lo_u)), p.value(float(hi_u))],
                "profile_share_of_prior": share,
                "posterior_std_over_prior_std": float(u.std() / math.sqrt(1 / 12)),
                "identifiable": share <= identifiable_share,
            }
        return out


def infer(emu: Emulator, measured: Curves, sigma_torque: np.ndarray, stride_sigma_rel: float = 0.03, n_samples: int = 6000, seed: int = 0, grid: int = 21) -> Posterior:
    """Posterior and profile likelihood of the parameters given the measured curves."""
    P = len(emu.params)
    y = features(measured)
    sigma = np.concatenate([sigma_torque, [max(stride_sigma_rel * abs(measured.stride or 1.0), 1e-9)]])
    sigma = np.sqrt(sigma**2 + emu.sigma_emu**2)
    use = ~np.isnan(y)

    def half_chi2(u: np.ndarray) -> float:
        if np.any(u < 0) or np.any(u > 1):
            return float("inf")
        r = (emu(u)[0] - y)[use] / sigma[use]
        return 0.5 * float(r @ r)

    rng = np.random.default_rng(seed)
    starts = [rng.random(P) for _ in range(8)]
    fits = [minimize(half_chi2, s, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 600}) for s in starts]
    best = min(fits, key=lambda r: r.fun)
    # random-walk Metropolis in the unit cube (uniform prior), adaptive step toward ~25 % acceptance
    x, fx = np.clip(best.x, 0, 1), best.fun
    step, acc, samples = 0.1, 0, []
    for i in range(n_samples + 2000):
        prop = x + rng.normal(0, step, P)
        fp = half_chi2(prop)
        if math.log(rng.random() + 1e-300) < fx - fp:
            x, fx, acc = prop, fp, acc + 1
        if i < 2000 and i % 100 == 99:
            step *= 1.3 if acc / 100 > 0.3 else 0.75 if acc / 100 < 0.15 else 1.0
            acc = 0
        if i >= 2000:
            samples.append(x.copy())
    g = np.linspace(0, 1, grid)
    prof = np.zeros((P, grid))
    for i in range(P):
        for j, v in enumerate(g):
            idx = [k for k in range(P) if k != i]

            def f(w: np.ndarray, i=i, v=v, idx=idx) -> float:
                u = np.empty(P)
                u[i] = v
                u[idx] = w
                return half_chi2(u)

            if not idx:
                prof[i, j] = f(np.array([]))
            else:
                starts = [best.x[idx]] + [np.clip(best.x[idx] + rng.normal(0, 0.15, len(idx)), 0, 1) for _ in range(2)]
                prof[i, j] = min(minimize(f, s0, method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-5, "maxiter": 200}).fun for s0 in starts)
    return Posterior(emu.params, np.array(samples), g, prof, 2 * float(best.fun), np.clip(best.x, 0, 1))
