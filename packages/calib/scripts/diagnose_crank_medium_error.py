"""H4-01 dynamical diagnosis of medium-speed open-loop rollout error on the public crank dataset.

1. Evaluates why the 2-parameter (viscous damping + bias) model from validate_crank_dynamics.py
   exhibits large holdout velocity NRMSE at medium speed (148.11% CW, 88.27% CCW) despite low
   error at fast speed (24.47% CW, 19.63% CCW).
2. Identifies a 3-parameter (viscous damping + dry Coulomb friction + bias) rotor model strictly
   on the 16 training trials (b >= 0, tau_c >= 0), and compares analytical zero-crossing-aware
   rollout against native MuJoCo (`damping` + `frictionloss`) rollout on the 16 holdout trials.
3. Quantifies the sensitivity of 16-second open-loop velocity integration to sub-0.1% full-scale
   force-transducer zero drift (ATI Gamma 15/50 full scale = 15 lbf = 66.723 N).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import mujoco
import numpy as np
from scipy.optimize import lsq_linear

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = ROOT / "experiments" / "external-crank-validation-plan-2026-11-04.json"
RAW_MANIFEST_PATH = ROOT / "experiments" / "external-crank-raw-trials-2026-11-04.json"
OUT_PATH = ROOT / "experiments" / "external-crank-medium-error-diagnosis-2026-11-04.json"
ATI_15_50_FULL_SCALE_N = 15.0 * 4.4482216152605  # 15 lbf in N = 66.7233 N


def _step_viscous(theta: float, omega: float, accel: float, damping: float, inertia: float, dt: float) -> tuple[float, float]:
    if dt <= 0.0:
        return theta, omega
    r = damping * dt / inertia
    decay = math.exp(-r)
    if abs(r) < 1e-5:
        phi1 = 1.0 - r / 2.0 + r * r / 6.0 - r * r * r / 24.0
        phi2 = 0.5 - r / 6.0 + r * r / 24.0 - r * r * r / 120.0
    else:
        phi1 = -math.expm1(-r) / r
        phi2 = (1.0 - phi1) / r
    theta_next = theta + dt * phi1 * omega + accel * dt * dt * phi2
    omega_next = decay * omega + accel * dt * phi1
    return theta_next, omega_next


def coulomb_rollout(
    torque: np.ndarray,
    dt: float,
    inertia: float,
    damping: float,
    coulomb: float,
    bias: float,
    theta0: float,
    omega0: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Exact scalar-rotor response to piecewise-constant torque under viscous + dry Coulomb friction + bias."""
    if dt <= 0 or inertia <= 0 or damping < 0 or coulomb < 0:
        raise ValueError("Invalid scalar rotor configuration")
    torque = np.asarray(torque, dtype=float)
    if torque.ndim != 1 or not np.isfinite(torque).all():
        raise ValueError("Torque must be a finite one-dimensional array")

    theta = np.empty(len(torque) + 1, dtype=float)
    omega = np.empty(len(torque) + 1, dtype=float)
    theta[0], omega[0] = float(theta0), float(omega0)

    for i, applied in enumerate(torque):
        th, om = theta[i], omega[i]
        net_drive = float(applied) - bias
        rem = dt

        if abs(om) > 0.0:
            s = 1.0 if om > 0.0 else -1.0
            tau_eff = net_drive - s * coulomb
            accel = tau_eff / inertia
            th_try, om_try = _step_viscous(th, om, accel, damping, inertia, rem)
            if om_try * om > 0.0:
                theta[i + 1], omega[i + 1] = th_try, om_try
                continue
            # Crossed zero within rem: find exact crossing time t_cross in (0, rem]
            if damping > 0.0 and abs(tau_eff - damping * om) > 1e-15:
                ratio = tau_eff / (tau_eff - damping * om)
                if 0.0 < ratio < 1.0:
                    t_cross = -inertia / damping * math.log(ratio)
                else:
                    t_cross = rem
            elif abs(accel) > 1e-15:
                t_cross = min(rem, max(0.0, -om / accel))
            else:
                t_cross = rem
            t_cross = min(rem, max(0.0, t_cross))
            th, _ = _step_viscous(th, om, accel, damping, inertia, t_cross)
            om = 0.0
            rem -= t_cross

        # At omega == 0 for remaining interval rem:
        if rem > 0.0:
            if abs(net_drive) <= coulomb:
                omega[i + 1] = 0.0
                theta[i + 1] = th
            else:
                s = 1.0 if net_drive > 0.0 else -1.0
                accel = (net_drive - s * coulomb) / inertia
                theta[i + 1], omega[i + 1] = _step_viscous(th, 0.0, accel, damping, inertia, rem)
        else:
            theta[i + 1], omega[i + 1] = th, om

    return theta, omega


def native_coulomb_rollout(
    torque: np.ndarray,
    dt: float,
    inertia: float,
    damping: float,
    coulomb: float,
    bias: float,
    theta0: float,
    omega0: float,
    substep: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Same scalar rotor with dry Coulomb frictionloss + viscous damping integrated by native MuJoCo."""
    n = round(dt / substep)
    if not math.isclose(n * substep, dt, rel_tol=1e-12):
        raise ValueError("Native step must divide the source row interval")
    model = mujoco.MjModel.from_xml_string(
        f"""<mujoco>
      <option timestep="{substep}" gravity="0 0 0" integrator="implicitfast" solver="Newton" tolerance="1e-12"/>
      <worldbody><body><joint name="crank" type="hinge" axis="0 0 1" damping="{damping}" frictionloss="{coulomb}"/>
        <inertial pos="0 0 0" mass="1" diaginertia="{inertia / 2} {inertia / 2} {inertia}"/>
      </body></worldbody></mujoco>"""
    )
    data = mujoco.MjData(model)
    data.qpos[0], data.qvel[0] = theta0, omega0
    theta, omega = [float(theta0)], [float(omega0)]
    for applied in torque:
        data.qfrc_applied[0] = float(applied) - bias
        mujoco.mj_step(model, data, nstep=n)
        theta.append(float(data.qpos[0]))
        omega.append(float(data.qvel[0]))
    return np.asarray(theta), np.asarray(omega)


def impulse_rows_coulomb(row: dict, inertia: float, dt: float, window_steps: int) -> tuple[np.ndarray, np.ndarray]:
    """Construct impulse-balance design matrix for [damping, coulomb, bias] on a training trial."""
    omega, torque = row["omega"], row["torque"]
    x, y = [], []
    for a in range(0, len(omega) - window_steps, window_steps):
        b = a + window_steps
        seg_w = 0.5 * (omega[a:b] + omega[a + 1 : b + 1])
        integrated_speed = float(dt * seg_w.sum())
        integrated_sign = float(dt * np.sign(seg_w).sum())
        x.append([integrated_speed, integrated_sign, window_steps * dt])
        y.append(float(dt * torque[a:b].sum() - inertia * (omega[b] - omega[a])))
    if not x:
        raise ValueError("Trial has no complete identification window")
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def fit_coulomb(trials: list[dict]) -> tuple[np.ndarray, float]:
    """Fit [damping, coulomb, bias] on training trials only, with damping >= 0 and coulomb >= 0."""
    if any(row["split"] != "train" for row in trials):
        raise ValueError("A holdout trial cannot enter parameter fitting")
    x = np.concatenate([row["X3"] / math.sqrt(len(row["Y3"])) for row in trials])
    y = np.concatenate([row["Y3"] / math.sqrt(len(row["Y3"])) for row in trials])
    solution = lsq_linear(x, y, bounds=([0.0, 0.0, -np.inf], [np.inf, np.inf, np.inf]), tol=1e-12)
    if not solution.success or not np.isfinite(solution.x).all() or np.linalg.matrix_rank(x) != 3:
        raise ValueError("Coulomb identification failed or is rank deficient")
    return solution.x, float(np.linalg.cond(x))


def compute_errors(theta: np.ndarray, omega: np.ndarray, observed: dict) -> dict[str, float]:
    return {
        "velocity_rmse_rad_s": float(np.sqrt(np.mean((omega - observed["omega"]) ** 2))),
        "velocity_nrmse": float(np.sqrt(np.mean((omega - observed["omega"]) ** 2) / np.mean(observed["omega"] ** 2))),
        "angle_rmse_rad": float(np.sqrt(np.mean((theta - observed["theta"]) ** 2))),
        "final_angle_error_rad": float(theta[-1] - observed["theta"][-1]),
        "final_velocity_error_rad_s": float(omega[-1] - observed["omega"][-1]),
    }


def main() -> None:
    plan = json.loads(PLAN_PATH.read_text())
    raw = json.loads(RAW_MANIFEST_PATH.read_text())
    dt = 1.0 / plan["source_parameters"]["row_frequency_hz"]
    radius = float(plan["source_parameters"]["radius_m"])
    inertia = float(plan["source_parameters"]["inertia_kg_m2"])
    trim = int(plan["rollout"]["common_trim_samples_each_end"])
    window_steps = round(plan["fit"]["impulse_window_s"] / dt)
    substep = float(plan["rollout"]["mujoco_primary_check"]["timestep_s"])

    rows = []
    for record in raw["files"]:
        a = np.loadtxt(record["local_path"])
        indices = np.arange(trim, len(a) - trim)
        row = {
            "name": record["name"],
            "condition": record["condition"],
            "split": record["split"],
            "theta": np.unwrap(a[:, 0])[indices],
            "omega": a[indices, 1] * math.tau,
            "torque": a[indices[:-1], 3] * radius,
            "ft_n": a[indices[:-1], 3],
        }
        if row["split"] == "train":
            row["X3"], row["Y3"] = impulse_rows_coulomb(row, inertia, dt, window_steps)
            # Also 2-parameter design matrix for direct comparison
            row["X2"] = row["X3"][:, [0, 2]]
            row["Y2"] = row["Y3"]
        rows.append(row)

    train_rows = [r for r in rows if r["split"] == "train"]
    holdout_rows = [r for r in rows if r["split"] == "holdout"]

    # 1. Fit 2-parameter viscous + bias model and 3-parameter viscous + Coulomb + bias model on train
    x2 = np.concatenate([r["X2"] / math.sqrt(len(r["Y2"])) for r in train_rows])
    y2 = np.concatenate([r["Y2"] / math.sqrt(len(r["Y2"])) for r in train_rows])
    sol2 = lsq_linear(x2, y2, bounds=([0.0, -np.inf], [np.inf, np.inf]), tol=1e-12)
    b2, bias2 = map(float, sol2.x)

    params3, cond3 = fit_coulomb(train_rows)
    b3, tau_c3, bias3 = map(float, params3)

    # 2. Condition-level mean dissipative torque analysis on training trials
    conditions = sorted({r["condition"] for r in rows})
    train_dissipation_by_condition = {}
    for cond in conditions:
        c_rows = [r for r in train_rows if r["condition"] == cond]
        mean_w = float(np.mean([np.mean(r["omega"]) for r in c_rows]))
        mean_tau_diss = float(
            np.mean([np.mean(r["torque"]) - inertia * (r["omega"][-1] - r["omega"][0]) / ((len(r["omega"]) - 1) * dt) for r in c_rows])
        )
        pred_viscous = b2 * mean_w + bias2
        pred_coulomb = b3 * mean_w + tau_c3 * math.copysign(1.0, mean_w) + bias3
        train_dissipation_by_condition[cond] = {
            "mean_omega_rad_s": mean_w,
            "observed_mean_dissipative_torque_nm": mean_tau_diss,
            "viscous_2param_predicted_nm": pred_viscous,
            "viscous_2param_residual_nm": mean_tau_diss - pred_viscous,
            "coulomb_3param_predicted_nm": pred_coulomb,
            "coulomb_3param_residual_nm": mean_tau_diss - pred_coulomb,
        }

    # 3. Evaluate holdout trials under both models + native MuJoCo Coulomb check + sensor zero-drift sensitivity
    per_trial_diagnostics = []
    for r in rows:
        th0, om0 = float(r["theta"][0]), float(r["omega"][0])
        th_v, om_v = coulomb_rollout(r["torque"], dt, inertia, b2, 0.0, bias2, th0, om0)
        th_c, om_c = coulomb_rollout(r["torque"], dt, inertia, b3, tau_c3, bias3, th0, om0)
        err_v = compute_errors(th_v, om_v, r)
        err_c = compute_errors(th_c, om_c, r)

        # Exact trial-specific mean torque residual (equivalent to tangential force zero offset Delta_Ft):
        duration_s = (len(r["theta"]) - 1) * dt
        mean_w = float(np.mean(r["omega"]))
        obs_diss_nm = float(np.mean(r["torque"]) - inertia * (r["omega"][-1] - r["omega"][0]) / duration_s)
        mod_diss_nm = b3 * mean_w + tau_c3 * math.copysign(1.0, mean_w) + bias3
        delta_tau_nm = obs_diss_nm - mod_diss_nm
        delta_ft_n = delta_tau_nm / radius

        entry = {
            "name": r["name"],
            "condition": r["condition"],
            "split": r["split"],
            "mean_omega_rad_s": mean_w,
            "mean_ft_n": float(np.mean(r["ft_n"])),
            "viscous_2param": err_v,
            "coulomb_3param": err_c,
            "implied_force_zero_offset_n": delta_ft_n,
            "implied_force_zero_offset_pct_of_full_scale": abs(delta_ft_n) / ATI_15_50_FULL_SCALE_N * 100.0,
            "steady_velocity_sensitivity_rad_s": abs(delta_tau_nm) / b3,
        }
        if r["split"] == "holdout":
            nth_c, nom_c = native_coulomb_rollout(r["torque"], dt, inertia, b3, tau_c3, bias3, th0, om0, substep)
            entry["native_coulomb_3param"] = compute_errors(nth_c, nom_c, r)
            entry["native_vs_analytic_max_vel_diff_rad_s"] = float(np.max(np.abs(nom_c - om_c)))
            entry["native_vs_analytic_max_angle_diff_rad"] = float(np.max(np.abs(nth_c - th_c)))
        per_trial_diagnostics.append(entry)

    def summarize_split(split_name: str, model_key: str) -> dict:
        chosen = [d for d in per_trial_diagnostics if d["split"] == split_name]
        pooled_rmse = float(np.sqrt(np.mean([d[model_key]["velocity_rmse_rad_s"] ** 2 for d in chosen])))
        by_cond = {
            c: float(np.sqrt(np.mean([d[model_key]["velocity_nrmse"] ** 2 for d in chosen if d["condition"] == c])))
            for c in conditions
        }
        return {"pooled_velocity_rmse_rad_s": pooled_rmse, "condition_velocity_nrmse": by_cond}

    holdout_offsets_n = [abs(d["implied_force_zero_offset_n"]) for d in per_trial_diagnostics if d["split"] == "holdout"]
    holdout_offsets_pct = [
        d["implied_force_zero_offset_pct_of_full_scale"] for d in per_trial_diagnostics if d["split"] == "holdout"
    ]

    output = {
        "date": "2026-11-04",
        "task": "H4-01",
        "h4_01_accepted": False,
        "models": {
            "viscous_2param": {
                "damping_nm_s_per_rad": b2,
                "torque_bias_nm": bias2,
                "train": summarize_split("train", "viscous_2param"),
                "holdout": summarize_split("holdout", "viscous_2param"),
            },
            "coulomb_3param": {
                "damping_nm_s_per_rad": b3,
                "coulomb_friction_nm": tau_c3,
                "torque_bias_nm": bias3,
                "condition_number": cond3,
                "train": summarize_split("train", "coulomb_3param"),
                "holdout": summarize_split("holdout", "coulomb_3param"),
                "native_mujoco_holdout": summarize_split("holdout", "native_coulomb_3param"),
            },
        },
        "train_dissipation_by_condition": train_dissipation_by_condition,
        "sensor_zero_drift_sensitivity": {
            "transducer_model": "ATI Gamma 15/50 6-DOF force/torque transducer",
            "transducer_full_scale_force_n": ATI_15_50_FULL_SCALE_N,
            "crank_radius_m": radius,
            "fitted_viscous_damping_nm_s_per_rad": b3,
            "mechanical_time_constant_s": inertia / b3,
            "rollout_duration_s": 15.995,
            "velocity_drift_per_0p05n_force_offset_rad_s": (0.05 * radius) / b3,
            "holdout_median_abs_force_offset_n": float(np.median(holdout_offsets_n)),
            "holdout_max_abs_force_offset_n": float(np.max(holdout_offsets_n)),
            "holdout_median_abs_force_offset_pct_full_scale": float(np.median(holdout_offsets_pct)),
            "holdout_max_abs_force_offset_pct_full_scale": float(np.max(holdout_offsets_pct)),
        },
        "trials": per_trial_diagnostics,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "trials"}, indent=2))


if __name__ == "__main__":
    main()
