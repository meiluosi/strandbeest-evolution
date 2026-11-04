"""Budgeted physical calibration: native training, independently checked surrogate, native validation.

Posterior/profile calculations use an emulator and are explicitly labelled as such. Validation
and local sensitivity always rerun the real forward model; no surrogate result is called a
successful native parameter recovery merely because its own training residual is small.
"""
from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.optimize import minimize
from scipy.stats import qmc

from .calibrate import parameter_registry, parameter_overrides, profile_source
from .conditions import validate_conditions


CHANNELS = ("foot_x", "foot_y", "omega", "x")


def trajectory_vector(prediction):
    return np.concatenate([prediction.foot_path[:, 0], prediction.foot_path[:, 1], prediction.omega, prediction.x_hip])


def channel_rms(residual, n):
    return {name: float(np.sqrt(np.mean(np.square(residual[i*n:(i+1)*n])))) for i, name in enumerate(CHANNELS)}


def calibrate_physical_twin(model, measurement, priors, *, n_samples=2500, burn_in=800, seed=0,
                            name="digital-twin-calibrated", emulator_points=16, validation_points=3,
                            profile_grid=11, training_fraction=0.7, identifiable_share=0.6,
                            sensitivity_snr=1.0, emulator_validation_sigma_limit=3.0):
    from .bayes import CalibrationProfile, CalibrationReport, _digital_twin_measurement
    document, observed, sigmas = _digital_twin_measurement(measurement)
    if document["design_id"] != model.design.id:
        raise ValueError("Measurement design_id must match the explicit forward Design")
    validate_conditions(document, model.scenario)
    alignment = document.get("provenance", {}).get("calibration", {}).get("alignment", {})
    if alignment.get("time_origin") != "drive_start" or alignment.get("foot_index") != model.foot_index or alignment.get("coordinates") != "world_xz_hip_relative":
        raise ValueError("Measurement alignment must declare drive_start, the selected foot_index, and world_xz_hip_relative coordinates")
    if document["synthetic"]:
        source = document.get("provenance", {}).get("calibration", {}).get("generator", {})
        for field in ("backend", "design_sha256", "scenario_sha256"):
            if source.get("forward_model", {}).get(field) != model.provenance[field]:
                raise ValueError(f"synthetic Measurement must preserve matching native forward_model {field}")
    if n_samples < 2 or burn_in < 0 or validation_points < 1 or profile_grid < 3 or not 0.4 <= training_fraction < 1:
        raise ValueError("invalid inference/validation budget")
    priors = dict({"pin_friction": (1e-4, 0.01), "contact_stiffness": (1e4, 1e7)} if priors is None else priors)
    names = list(priors)
    if not names:
        raise ValueError("at least one supported parameter is required")
    for key, limits in priors.items():
        if len(limits) != 2 or not all(math.isfinite(v) and v > 0 for v in limits) or limits[1] <= limits[0]:
            raise ValueError(f"invalid positive log prior for {key}")
        parameter_overrides({key: limits[0]}, model.design)
        parameter_overrides({key: limits[1]}, model.design)
    p = len(names)
    if emulator_points < p+3:
        raise ValueError("emulator_points must be at least number of parameters + 3")
    lo = np.log([priors[k][0] for k in names]); span = np.log([priors[k][1] for k in names])-lo
    values = lambda u: {key: float(np.clip(np.exp(lo[i]+span[i]*u[i]), *priors[key])) for i, key in enumerate(names)}
    model.scenario_for(values(np.full(p, 0.5)))  # reject competing/inactive mappings before using a simulation budget
    times = observed["t"]; n = len(times)
    if n < 6:
        raise ValueError("at least six observations are required for independent time holdout")
    fit_n = min(n-2, max(3, int(n*training_fraction)))
    use = np.tile(np.arange(n) < fit_n, 4)
    y_obs = np.concatenate([observed["foot_path"][:, 0], observed["foot_path"][:, 1], observed["omega"], observed["x_hip"]])
    noise = np.repeat([sigmas["foot_x"], sigmas["foot_y"], sigmas["omega"], sigmas["hip"]], n)
    started = time.perf_counter(); before_calls = model.native_calls; before_seconds = model.native_seconds
    implementation = model.provenance["implementation"]
    train = np.linspace(0, 1, emulator_points)[:, None] if p == 1 else qmc.LatinHypercube(p, seed=seed).random(emulator_points)
    y = np.array([trajectory_vector(model.predict(values(point), times)) for point in train])
    if not np.isfinite(y).all():
        raise ValueError("native training produced nonfinite trajectory data")
    emulator = RBFInterpolator(train, y, kernel="thin_plate_spline", degree=1, smoothing=1e-12)
    errors = []
    for i in range(len(train)):
        keep = np.arange(len(train)) != i
        loo = RBFInterpolator(train[keep], y[keep], kernel="thin_plate_spline", degree=1, smoothing=1e-12)
        errors.append(loo(train[i:i+1])[0]-y[i])
    sigma_emu = np.sqrt(np.mean(np.square(errors), axis=0))
    sigma = np.sqrt(noise**2 + sigma_emu**2)
    # Independent parameter-space holdout never contributes to emulator training or the likelihood.
    holdout = qmc.LatinHypercube(p, seed=seed+711).random(validation_points)
    native_holdout = np.array([trajectory_vector(model.predict(values(point), times)) for point in holdout])
    holdout_errors = emulator(holdout)-native_holdout
    holdout_sigma_rmse = float(np.sqrt(np.mean((holdout_errors/noise)**2)))

    def half_chi2(u):
        if np.any(u < 0) or np.any(u > 1): return float("inf")
        residual = (emulator(np.atleast_2d(u))[0]-y_obs)[use]/sigma[use]
        return float(residual @ residual)/2

    rng = np.random.default_rng(seed)
    fits = [minimize(half_chi2, start, method="Nelder-Mead", options={"maxiter": 500, "xatol": 1e-5, "fatol": 1e-5})
            for start in [np.full(p, 0.5), *rng.random((4, p))]]
    optimum = min(fits, key=lambda result: result.fun)
    best = np.clip(optimum.x, 0, 1)
    x = best.copy(); score = half_chi2(x); step_scale = 0.06; accepted = 0; block_accepts = 0
    samples = []; history = []
    for i in range(burn_in+n_samples):
        proposal = x+rng.normal(0, step_scale, p); value = half_chi2(proposal)
        if math.log(rng.random()+1e-300) < score-value:
            x, score = proposal, value; block_accepts += 1
            if i >= burn_in: accepted += 1
        if i < burn_in and i % 50 == 49:
            step_scale *= 1.2 if block_accepts/50 > 0.35 else 0.8 if block_accepts/50 < 0.18 else 1
            block_accepts = 0
        if i >= burn_in:
            samples.append(x.copy()); history.append(-score)
    sample_u = np.array(samples); sample_natural = np.exp(lo+span*sample_u)
    means = {key: float(sample_natural[:, i].mean()) for i, key in enumerate(names)}
    stds = {key: float(sample_natural[:, i].std(ddof=1)) for i, key in enumerate(names)}
    ci95 = {key: tuple(float(x) for x in np.quantile(sample_natural[:, i], [0.025, 0.975])) for i, key in enumerate(names)}
    grid = np.linspace(0, 1, profile_grid); profiles = []
    for i in range(p):
        other = [j for j in range(p) if j != i]; row = []
        for value in grid:
            def objective(rest):
                trial = best.copy(); trial[i] = value; trial[other] = rest
                return half_chi2(trial)
            row.append(minimize(objective, best[other], method="Nelder-Mead", options={"maxiter": 250}).fun if other else objective(np.array([])))
        profiles.append(np.array(row))
    map_values = values(best)
    native_map = trajectory_vector(model.predict(map_values, times))
    # Sensitivities are native finite differences in dimensionless log-prior coordinates.
    jacobian = []
    for i in range(p):
        plus = best.copy(); minus = best.copy(); plus[i] = min(1, best[i]+0.02); minus[i] = max(0, best[i]-0.02)
        a = trajectory_vector(model.predict(values(plus), times)); b = trajectory_vector(model.predict(values(minus), times))
        jacobian.append(((a-b)/(plus[i]-minus[i])/noise)[use])
    jacobian = np.column_stack(jacobian)
    _, singular, vectors = np.linalg.svd(jacobian, full_matrices=False)
    weak = vectors[singular < sensitivity_snr]
    acceptance = accepted/n_samples
    uncertainty = {}
    for i, key in enumerate(names):
        eligible = profiles[i]-min(profiles[i].min(), optimum.fun) <= 1.92
        if not eligible.any(): eligible[np.argmin(profiles[i])] = True
        width = 1/(profile_grid-1)/2
        low = max(0.0, grid[eligible].min()-width); high = min(1.0, grid[eligible].max()+width)
        identifiable = (high-low <= identifiable_share and np.linalg.norm(jacobian[:, i]) >= sensitivity_snr
                        and not (weak.size and np.any(np.abs(weak[:, i]) > 0.25))
                        and holdout_sigma_rmse <= emulator_validation_sigma_limit and acceptance > 0.01)
        uncertainty[key] = {"ci95": list(ci95[key]), "profile_ci95": [float(np.exp(lo[i]+span[i]*low)), float(np.exp(lo[i]+span[i]*high))],
                            "profile_share_of_prior": float(high-low), "identifiable": bool(identifiable)}
    residual = native_map-y_obs
    residual_foot = np.column_stack([residual[:n], residual[n:2*n]])
    rms = float(np.sqrt(np.mean(np.sum(residual_foot**2, axis=1))))
    profile = CalibrationProfile(parameters=map_values, name=name, uncertainty=uncertainty,
        scenario=model.scenario.model_dump(mode="json", exclude_unset=True),
        provenance={"measurement_ids": [document["id"]], **profile_source(model.design), "synthetic": document["synthetic"],
                    "method": f"MuJoCo trajectory emulator + MCMC; {emulator_points} native training runs, {validation_points} independent emulator checks, native MAP/time-holdout validation",
                    "residual": rms})
    model.apply_profile(profile.to_dict())  # schema-valid executable writeback, not a parameter bag for another model
    registry = parameter_registry(model.design)
    native_runs = model.native_runs[before_calls:]
    if (model.provenance["implementation"] != implementation
            or any(not row["implementation_unchanged"] or row["implementation"] != implementation for row in native_runs)):
        raise ValueError("implementation changed during physical calibration; do not mix results from different implementations")
    validation = {"forward_model": model.provenance, "native_calls": model.native_calls-before_calls,
                  "native_runs": native_runs,
                  "native_seconds": model.native_seconds-before_seconds, "total_seconds": time.perf_counter()-started,
                  "parameter_mapping": {key: {"unit": registry[key].unit, "scenario_paths": list(registry[key].scenario_paths), "limitation": registry[key].limitation} for key in names},
                  "training_parameter_points": train.tolist(), "independent_parameter_points": holdout.tolist(),
                  "emulator_loo_rms": channel_rms(sigma_emu, n),
                  "emulator_holdout_rms": {key: float(np.sqrt(np.mean(holdout_errors[:, i*n:(i+1)*n]**2))) for i, key in enumerate(CHANNELS)},
                  "emulator_holdout_normalized_rmse": holdout_sigma_rmse,
                  "fit_time_indices": list(range(fit_n)), "held_out_time_indices": list(range(fit_n, n)),
                  "native_map_rms": channel_rms(residual, n),
                  "native_time_holdout_rms": channel_rms(residual.reshape(4, n)[:, fit_n:].ravel(), n-fit_n),
                  "native_time_holdout_normalized_rmse": float(np.sqrt(np.mean((residual[~use]/noise[~use])**2))),
                  "native_sensitivity_singular_values": singular.tolist(),
                  "native_sensitivity_directions": [{key: float(row[i]) for i, key in enumerate(names)} for row in vectors],
                  "diagnostic_thresholds": {"profile_share": identifiable_share, "sensitivity_snr": sensitivity_snr, "emulator_validation_sigma_limit": emulator_validation_sigma_limit},
                  "limitations": ["Synthetic recovery is not validation against a physical build.", "Posterior is conditional on the emulator and independent pointwise Gaussian noise assumption; one MCMC chain is not a convergence certificate.", "bar_flexibility has no physical backend mapping and is rejected; contact compliance is not bar elasticity or sand granular flow."]}
    return CalibrationReport(profile=profile, parameter_means=means, parameter_stds=stds, credible_intervals_95=ci95,
                             acceptance_rate=acceptance, n_samples=n_samples, map_estimate=map_values, residual_rms=rms,
                             measurement=document, samples={key: sample_natural[:, i] for i, key in enumerate(names)},
                             log_posterior_history=history, validation=validation)
