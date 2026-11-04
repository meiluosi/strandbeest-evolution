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

import copy
import json
import math
import warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.optimize import minimize
from scipy.stats import qmc

from strandbeest_common.ids import new_ulid
from .forward import DigitalTwinModel, DigitalTwinTrajectory
from strandbeest_common.schemas import validate

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


# -----------------------------------------------------------------------------
# M8-02: Rig-to-Sim Bayesian Calibration & Digital Twin Loop
# -----------------------------------------------------------------------------

@dataclass
class CalibrationProfile:
    """A calibrated parameter set with its provenance and uncertainty, matching profile.schema.json."""

    parameters: dict[str, float]
    provenance: dict[str, Any]
    uncertainty: dict[str, Any] = field(default_factory=dict)
    name: str = "digital-twin-profile"
    id: str = field(default_factory=new_ulid)
    schema_version: int = 2
    scenario: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        doc = {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "parameters": {k: float(v) for k, v in self.parameters.items()},
            "provenance": dict(self.provenance),
        }
        if self.uncertainty:
            doc["uncertainty"] = self.uncertainty
        if self.scenario is not None:
            doc["scenario"] = copy.deepcopy(self.scenario)
        validate("profile", doc)
        return doc


@dataclass
class CalibrationReport:
    """Structured report of Bayesian MCMC inverse parameter estimation."""

    profile: CalibrationProfile
    parameter_means: dict[str, float]
    parameter_stds: dict[str, float]
    credible_intervals_95: dict[str, tuple[float, float]]
    acceptance_rate: float
    n_samples: int
    map_estimate: dict[str, float]
    residual_rms: float
    measurement: dict[str, Any]
    samples: dict[str, np.ndarray] = field(default_factory=dict)
    log_posterior_history: list[float] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "parameter_means": self.parameter_means,
            "parameter_stds": self.parameter_stds,
            "credible_intervals_95": {k: list(v) for k, v in self.credible_intervals_95.items()},
            "acceptance_rate": self.acceptance_rate,
            "n_samples": self.n_samples,
            "map_estimate": self.map_estimate,
            "residual_rms": self.residual_rms,
            "measurement": copy.deepcopy(self.measurement),
            "validation": copy.deepcopy(self.validation),
        }

    def save_json(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))

    def summary(self) -> str:
        lines = [
            f"=== Calibration Report ({self.profile.name}) ===",
            f"Residual RMS: {self.residual_rms:.4e}",
            f"MCMC Samples: {self.n_samples} (acceptance rate: {self.acceptance_rate * 100:.1f}%)",
            "Parameters (mean +/- std [95% CI]):",
        ]
        for k in self.parameter_means:
            m = self.parameter_means[k]
            s = self.parameter_stds[k]
            ci = self.credible_intervals_95[k]
            lines.append(f"  {k:15s}: {m:.4e} +/- {s:.4e}  [{ci[0]:.4e}, {ci[1]:.4e}]")
        return "\n".join(lines)


def log_likelihood_digital_twin(
    model: DigitalTwinModel,
    obs_data: Any,
    params: dict[str, float] | Sequence[float],
    sigmas: dict[str, float] | None = None,
) -> float:
    """Evaluate log-likelihood based on residual distance between tracked video trajectories and simulation predictions."""
    sigmas = sigmas or {}
    sig_foot = float(sigmas.get("foot", 0.0008))  # synthetic experiment default only
    sig_foot_x = float(sigmas.get("foot_x", sig_foot))
    sig_foot_y = float(sigmas.get("foot_y", sig_foot))
    sig_omega = float(sigmas.get("omega", 0.05))  # ~0.05 rad/s angular velocity precision
    sig_hip = float(sigmas.get("hip", 0.001))  # ~1 mm body position precision

    t = obs_data.t if hasattr(obs_data, "t") else np.asarray(obs_data["t"])
    pred = model.predict(params, t)

    if hasattr(obs_data, "foot_path"):
        obs_foot = np.asarray(obs_data.foot_path)
    else:
        obs_foot = np.asarray(obs_data["foot_path"])

    if hasattr(obs_data, "omega"):
        obs_omega = np.asarray(obs_data.omega)
    else:
        obs_omega = np.asarray(obs_data["omega"])

    obs_hip = None
    if hasattr(obs_data, "trajectories") and "hip" in obs_data.trajectories:
        obs_hip = obs_data.trajectories["hip"][:, 0]
    elif isinstance(obs_data, dict) and "x_hip" in obs_data:
        obs_hip = np.asarray(obs_data["x_hip"])

    # Residuals
    r_foot_x = obs_foot[:, 0] - pred.foot_path[:, 0]
    r_foot_y = obs_foot[:, 1] - pred.foot_path[:, 1]
    r_omega = obs_omega - pred.omega

    chi2 = np.sum(r_foot_x**2) / sig_foot_x**2 + np.sum(r_foot_y**2) / sig_foot_y**2 + np.sum(r_omega**2) / sig_omega**2

    if obs_hip is not None:
        r_hip = obs_hip - pred.x_hip
        chi2 += np.sum(r_hip**2) / (sig_hip**2)

    return -0.5 * float(chi2)


def simulate_digital_twin_trajectories(
    model: DigitalTwinModel,
    truth: dict[str, float],
    t: np.ndarray | None = None,
    noise_sigma: float = 0.0008,
    seed: int = 0,
    *,
    design_id: str | None = None,
    measurement_id: str | None = None,
) -> Any:
    """Generate synthetic observations and their actual Measurement asset.

    ``design_id`` identifies the design being simulated. The returned
    ``measurement`` must be retained with calibration results, rather than
    inventing an unrelated measurement id when the fit finishes.
    """
    from .conditions import scenario_conditions
    if design_id is not None and design_id != model.design.id:
        raise ValueError("synthetic Measurement design_id must match the explicit forward Design")
    design_id = model.design.id
    if not math.isfinite(noise_sigma) or noise_sigma <= 0:
        raise ValueError("noise_sigma must be positive for a noisy synthetic Measurement")
    if t is None:
        t = np.linspace(0.0, 1.5, 60)
    pred = model.predict(truth, t)
    rng = np.random.default_rng(seed)

    foot_noisy = pred.foot_path + rng.normal(0.0, noise_sigma, pred.foot_path.shape)
    omega_noisy = pred.omega + rng.normal(0.0, noise_sigma * 50.0, pred.omega.shape)
    hip_x_noisy = pred.x_hip + rng.normal(0.0, noise_sigma, pred.x_hip.shape)

    class SyntheticObs:
        def __init__(self):
            self.t = t
            self.omega = omega_noisy
            self.foot_path = foot_noisy
            self.crank_angle = pred.crank_angle
            self.trajectories = {
                "hip": np.column_stack([hip_x_noisy, np.zeros_like(hip_x_noisy)]),
                "foot": foot_noisy,
            }
            self.fps = float((len(t) - 1) / (t[-1] - t[0]))
            self.frames = len(t)
            self.detected_fractions = {"hip": 1.0, "crank": 1.0, "foot": 1.0}
            self.metres_per_pixel = 0.00033
            self.warnings: list[str] = []
            self.synthetic = True
            self.measurement = {
                "schema_version": 2,
                "id": measurement_id or new_ulid(),
                "design_id": design_id,
                "name": f"synthetic-digital-twin-seed-{seed}",
                "synthetic": True,
                "conditions": scenario_conditions(model.scenario),
                "channels": {
                    "t": t.tolist(), "psi": pred.crank_angle.tolist(), "omega": omega_noisy.tolist(),
                    "foot_x": foot_noisy[:, 0].tolist(), "foot_y": foot_noisy[:, 1].tolist(), "x": hip_x_noisy.tolist(),
                },
                "provenance": {
                    "source": "simulator",
                    "notes": "Synthetic parameter-recovery experiment; no physical measurement or validation.",
                    "calibration": {
                        "units": {"t": "s", "psi": "rad", "omega": "rad/s", "foot_x": "m", "foot_y": "m", "x": "m"},
                        "uncertainty": {"foot_x": noise_sigma, "foot_y": noise_sigma, "omega": noise_sigma * 50.0, "x": noise_sigma},
                        "uncertainty_kind": "absolute_1sigma",
                        "alignment": {"time_origin": "drive_start", "foot_index": model.foot_index, "coordinates": "world_xz_hip_relative"},
                        "generator": {"model": "PhysicsBackend observation adapter", "seed": seed, "truth": dict(truth), "forward_model": model.provenance},
                    },
                },
            }
            validate("measurement", self.measurement)

    return SyntheticObs()


def _digital_twin_measurement(obs_data: Any) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, float]]:
    """Validate the source asset before spending a calibration budget on it."""
    doc = obs_data if isinstance(obs_data, dict) and "channels" in obs_data else getattr(obs_data, "measurement", None)
    if not isinstance(doc, dict):
        raise ValueError("digital-twin calibration requires a Measurement document; convert tracking with to_measurement first")
    validate("measurement", doc)
    doc = copy.deepcopy(doc)
    ch = doc["channels"]
    units = {"t": "s", "omega": "rad/s", "foot_x": "m", "foot_y": "m", "x": "m"}
    missing = set(units) - ch.keys()
    if missing:
        raise ValueError(f"Measurement lacks digital-twin channels: {', '.join(sorted(missing))}")
    arrays = {key: np.asarray(ch[key], dtype=float) for key in units}
    t = arrays["t"]
    if t.ndim != 1 or len(t) < 2 or not np.all(np.diff(t) > 0):
        raise ValueError("Measurement timestamps must be strictly increasing")
    if any(a.shape != t.shape or not np.isfinite(a).all() for a in arrays.values()):
        raise ValueError("Measurement channels must be finite equal-length arrays")
    prov = doc.get("provenance", {})
    cal = prov.get("calibration", {})
    for key, unit in units.items():
        if cal.get("units", {}).get(key) != unit:
            raise ValueError(f"Measurement channel {key} must explicitly declare unit {unit}")
    if cal.get("uncertainty_kind") != "absolute_1sigma":
        raise ValueError("Measurement uncertainty_kind must be absolute_1sigma")
    uncertainty = cal.get("uncertainty", {})
    for key in ("foot_x", "foot_y", "omega", "x"):
        value = uncertainty.get(key)
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Measurement channel {key} requires positive absolute 1-sigma uncertainty")
    if doc["synthetic"]:
        if prov.get("source") != "simulator":
            raise ValueError("synthetic Measurement must declare source=simulator")
    else:
        required = [key for key in ("instrument", "measured_on", "calibrated_on", "camera") if not cal.get(key)]
        if required or not prov.get("raw_file") or prov.get("source") not in ("rig", "manual"):
            raise ValueError("real video Measurement needs source=rig/manual, raw_file and calibration fields: "
                             + ", ".join(required or ["instrument, measured_on, calibrated_on, camera"]))
        for key in ("measured_on", "calibrated_on"):
            date.fromisoformat(cal[key])
        camera = cal["camera"]
        matrix = np.asarray(camera.get("camera_matrix", []), dtype=float)
        size = np.asarray(camera.get("image_size", []))
        distortion = np.asarray(camera.get("dist_coeffs", []), dtype=float)
        if (matrix.shape != (3, 3) or not np.isfinite(matrix).all() or np.linalg.det(matrix) == 0
                or size.shape != (2,) or not np.all(size > 0) or not distortion.size or not np.isfinite(distortion).all()):
            raise ValueError("camera calibration needs a finite nonsingular 3x3 matrix, distortion coefficients and image size")
    observations = {"t": t, "omega": arrays["omega"], "foot_path": np.column_stack([arrays["foot_x"], arrays["foot_y"]]), "x_hip": arrays["x"]}
    sigmas = {"foot_x": float(uncertainty["foot_x"]), "foot_y": float(uncertainty["foot_y"]),
              "omega": float(uncertainty["omega"]), "hip": float(uncertainty["x"])}
    return doc, observations, sigmas


def calibrate_digital_twin_bayes(
    model: DigitalTwinModel,
    obs_data: Any,
    priors: dict[str, tuple[float, float]] | None = None,
    *,
    n_samples: int = 2500,
    burn_in: int = 800,
    seed: int = 0,
    name: str = "digital-twin-calibrated",
    emulator_points: int = 16,
    validation_points: int = 3,
    profile_grid: int = 11,
    training_fraction: float = 0.7,
) -> CalibrationReport:
    """Fit registered physical parameters using native training and independent native validation.

    The posterior uses a trajectory emulator and is labelled accordingly. The final MAP,
    independent parameter-space holdout, time holdout, and sensitivity directions use the
    original Design/Scenario/MuJoCo model. Video data must state its drive-start time origin
    and selected foot index. Real-world validation remains separate from synthetic recovery.
    """
    from .physical_inference import calibrate_physical_twin
    return calibrate_physical_twin(model, obs_data, priors, n_samples=n_samples, burn_in=burn_in,
                                  seed=seed, name=name, emulator_points=emulator_points,
                                  validation_points=validation_points, profile_grid=profile_grid,
                                  training_fraction=training_fraction)
