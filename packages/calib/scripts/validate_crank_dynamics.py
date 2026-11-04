"""Predeclared whole-trial crank identification and open-loop holdout diagnostics.

Uses only mechanical columns of the public data. No Measurement/Profile is
created, and unknown instrument uncertainty is not replaced by fit uncertainty.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

import mujoco
import numpy as np
from scipy.optimize import lsq_linear


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_records(selected, records):
    """The acquisition manifest cannot redefine a locked split or condition."""
    expected = {row['name']: row for row in selected}
    if len(expected) != len(selected) or len(records) != len(selected):
        raise ValueError('Trial manifest length or uniqueness differs from the locked plan')
    if {r['name'] for r in records} != set(expected):
        raise ValueError('Trial names differ from the locked plan')
    for record in records:
        if any(record.get(key) != value for key, value in expected[record['name']].items()):
            raise ValueError('Trial metadata or split differs from the locked plan')


def linear_rollout(torque, dt, inertia, damping, bias, theta0, omega0):
    """Exact scalar-rotor response to left-held torque; no measured state resets."""
    if dt <= 0 or inertia <= 0 or damping < 0:
        raise ValueError('Invalid scalar rotor configuration')
    torque = np.asarray(torque, dtype=float)
    if torque.ndim != 1 or not np.isfinite(torque).all():
        raise ValueError('Torque must be a finite one-dimensional array')
    r = damping * dt / inertia
    decay = math.exp(-r)
    if abs(r) < 1e-5:
        phi1 = 1 - r / 2 + r*r / 6 - r*r*r / 24
        phi2 = .5 - r / 6 + r*r / 24 - r*r*r / 120
    else:
        phi1 = -math.expm1(-r) / r
        phi2 = (1 - phi1) / r
    theta, omega = np.empty(len(torque) + 1), np.empty(len(torque) + 1)
    theta[0], omega[0] = theta0, omega0
    for i, applied in enumerate(torque):
        acceleration = (applied - bias) / inertia
        theta[i+1] = theta[i] + dt * phi1 * omega[i] + acceleration * dt*dt * phi2
        omega[i+1] = decay * omega[i] + acceleration * dt * phi1
    return theta, omega


def native_rollout(torque, dt, inertia, damping, bias, theta0, omega0, substep):
    """Same declared scalar rotor, integrated by the project's native MuJoCo version."""
    n = round(dt / substep)
    if not math.isclose(n * substep, dt, rel_tol=1e-12):
        raise ValueError('Native step must divide the source row interval')
    model = mujoco.MjModel.from_xml_string(f'''<mujoco>
      <option timestep="{substep}" gravity="0 0 0" integrator="implicitfast" solver="Newton" tolerance="1e-12"/>
      <worldbody><body><joint name="crank" type="hinge" axis="0 0 1" damping="{damping}"/>
        <inertial pos="0 0 0" mass="1" diaginertia="{inertia/2} {inertia/2} {inertia}"/>
      </body></worldbody></mujoco>''')
    data = mujoco.MjData(model)
    data.qpos[0], data.qvel[0] = theta0, omega0
    theta, omega = [theta0], [omega0]
    for applied in torque:
        data.qfrc_applied[0] = applied - bias
        mujoco.mj_step(model, data, nstep=n)
        theta.append(float(data.qpos[0]))
        omega.append(float(data.qvel[0]))
    return np.asarray(theta), np.asarray(omega)


def impulse_rows(row, inertia, dt, window_steps):
    """Measured omega is used only for identification, never as future rollout input."""
    omega, torque = row['omega'], row['torque']
    x, y = [], []
    for a in range(0, len(omega) - window_steps, window_steps):
        b = a + window_steps
        integrated_speed = .5 * dt * (omega[a:b] + omega[a+1:b+1]).sum()
        x.append([integrated_speed, window_steps * dt])
        y.append(dt * torque[a:b].sum() - inertia * (omega[b] - omega[a]))
    if not x:
        raise ValueError('Trial has no complete identification window')
    return np.asarray(x), np.asarray(y)


def fit(trials):
    """Equal total squared-error weight per complete training trial."""
    if any(row['split'] != 'train' for row in trials):
        raise ValueError('A holdout trial cannot enter parameter fitting')
    x = np.concatenate([row['X'] / math.sqrt(len(row['Y'])) for row in trials])
    y = np.concatenate([row['Y'] / math.sqrt(len(row['Y'])) for row in trials])
    solution = lsq_linear(x, y, bounds=([0, -np.inf], [np.inf, np.inf]), tol=1e-12)
    if not solution.success or not np.isfinite(solution.x).all() or np.linalg.matrix_rank(x) != 2:
        raise ValueError('Identification failed or is rank deficient')
    return solution.x, float(np.linalg.cond(x))


def errors(theta, omega, observed):
    return dict(velocity_rmse_rad_s=float(np.sqrt(np.mean((omega - observed['omega'])**2))),
        velocity_nrmse=float(np.sqrt(np.mean((omega - observed['omega'])**2) / np.mean(observed['omega']**2))),
        angle_rmse_rad=float(np.sqrt(np.mean((theta - observed['theta'])**2))),
        final_angle_error_rad=float(theta[-1] - observed['theta'][-1]),
        final_velocity_error_rad_s=float(omega[-1] - observed['omega'][-1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--raw-manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    raw = json.loads(args.raw_manifest.read_text())
    assert raw['complete'] and raw['plan_sha256'] == digest(args.plan)
    assert len(raw['files']) == len(plan['selected_trials']) == 32
    validate_records(plan['selected_trials'], raw['files'])
    source = plan['analysis_source']
    assert digest(source['local_path']) == source['sha256']
    args.output.mkdir(parents=True, exist_ok=False)
    # Verify and load all selected records without skipping any failed record.
    loaded = {}
    for record in raw['files']:
        assert digest(record['local_path']) == record['sha256']
        a = np.loadtxt(record['local_path'])
        if a.ndim != 2 or a.shape[1] != 10 or not np.isfinite(a[:, :8]).all():
            raise ValueError(f"Invalid mechanical input: {record['name']}")
        loaded[record['name']] = a
    dt = 1 / plan['source_parameters']['row_frequency_hz']
    radius = plan['source_parameters']['radius_m']
    base_inertia = plan['source_parameters']['inertia_kg_m2']
    trim = plan['rollout']['common_trim_samples_each_end']
    count = round(plan['fit']['impulse_window_s'] / dt)
    hashes = {str(args.plan): digest(args.plan), str(args.raw_manifest): digest(args.raw_manifest),
              str(Path(__file__)): digest(__file__), source['local_path']: digest(source['local_path'])}
    result = dict(complete=False, plan_path=str(args.plan), plan_sha256=digest(args.plan),
        raw_manifest_path=str(args.raw_manifest), raw_manifest_sha256=digest(args.raw_manifest),
        source_sha256=hashes, numpy=importlib.metadata.version('numpy'), scipy=importlib.metadata.version('scipy'),
        mujoco=mujoco.mj_versionString(), train_trials=16, holdout_trials=16,
        measurement_created=False, profile_created=False, h4_01_accepted=False,
        variants=[], all_trials_retained=True, physiological_columns_analysed=False)
    target = args.output / 'manifest.json'
    def save():
        target.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    save()
    for scale in plan['sensitivity']['inertia_multipliers']:
        inertia = scale * base_inertia
        for offset in plan['sensitivity']['force_row_offsets']:
            primary = scale == 1 and offset == 0
            rows = []
            for record in raw['files']:
                a = loaded[record['name']]
                indices = np.arange(trim, len(a) - trim)
                row = dict(name=record['name'], condition=record['condition'], split=record['split'],
                    theta=np.unwrap(a[:, 0])[indices], omega=a[indices, 1] * math.tau,
                    torque=a[indices[:-1] + offset, 3] * radius)
                if row['split'] == 'train':
                    row['X'], row['Y'] = impulse_rows(row, inertia, dt, count)
                rows.append(row)
            training = [r for r in rows if r['split'] == 'train']
            parameters, condition_number = fit(training)
            damping, bias = map(float, parameters)
            variant = dict(inertia_multiplier=scale, force_row_offset=offset, primary=primary,
                damping_nm_s=damping, torque_bias_nm=bias, training_matrix_condition=condition_number,
                rows=[], confidence=None)
            if primary:
                rng = np.random.default_rng(plan['fit']['bootstrap_seed'])
                conditions = sorted({r['condition'] for r in training})
                groups = [[r for r in training if r['condition'] == c] for c in conditions]
                bootstrap = []
                for _ in range(plan['fit']['bootstrap_replicates']):
                    sample = [group[i] for group in groups for i in rng.integers(0, len(group), len(group))]
                    estimate, _ = fit(sample)
                    bootstrap.append(estimate.tolist())
                variant['confidence'] = {'method': plan['fit']['bootstrap_unit'],
                    'interpretation': plan['fit']['uncertainty_scope'],
                    'percentiles_2p5_97p5': np.quantile(bootstrap, [.025, .975], axis=0).tolist(),
                    'samples': bootstrap}
            arrays = {}
            for index, row in enumerate(rows):
                initial = row['theta'][0], row['omega'][0]
                theta0, omega0 = linear_rollout(row['torque'], dt, inertia, 0, 0, *initial)
                theta1, omega1 = linear_rollout(row['torque'], dt, inertia, damping, bias, *initial)
                report = dict(name=row['name'], condition=row['condition'], split=row['split'],
                    samples=len(row['theta']), duration_s=(len(row['theta']) - 1)*dt,
                    baseline=errors(theta0, omega0, row), fitted=errors(theta1, omega1, row))
                if primary and row['split'] == 'holdout':
                    native_theta, native_omega = native_rollout(row['torque'], dt, inertia, damping, bias,
                        *initial, plan['rollout']['mujoco_primary_check']['timestep_s'])
                    report['native_fitted'] = errors(native_theta, native_omega, row)
                    report['native_vs_analytic'] = dict(
                        max_angle_difference_rad=float(np.max(np.abs(native_theta-theta1))),
                        max_velocity_difference_rad_s=float(np.max(np.abs(native_omega-omega1))))
                    arrays[f'{index}_native_theta'], arrays[f'{index}_native_omega'] = native_theta, native_omega
                for name, values in [('theta', row['theta']), ('omega', row['omega']), ('torque', row['torque']),
                    ('baseline_theta', theta0), ('baseline_omega', omega0), ('fitted_theta', theta1), ('fitted_omega', omega1)]:
                    arrays[f'{index}_{name}'] = values
                variant['rows'].append(report)
            for split in ['train', 'holdout']:
                chosen = [r for r in variant['rows'] if r['split'] == split]
                # Equal whole-trial weighting, as declared for fitting.
                before = float(np.sqrt(np.mean([r['baseline']['velocity_rmse_rad_s']**2 for r in chosen])))
                after = float(np.sqrt(np.mean([r['fitted']['velocity_rmse_rad_s']**2 for r in chosen])))
                by_condition = {c: float(np.sqrt(np.mean([r['fitted']['velocity_nrmse']**2 for r in chosen if r['condition'] == c])))
                    for c in sorted({r['condition'] for r in chosen})}
                variant[split] = dict(baseline_velocity_rmse_rad_s=before, fitted_velocity_rmse_rad_s=after,
                    rmse_reduction_fraction=1-after/before, condition_velocity_nrmse=by_condition)
            arrays_path = args.output / f'inertia{scale}-offset{offset}.npz'
            np.savez_compressed(arrays_path, **arrays)
            variant.update(arrays_path=str(arrays_path), arrays_sha256=digest(arrays_path))
            result['variants'].append(variant)
            save()
            print(json.dumps({k: variant[k] for k in ['inertia_multiplier', 'force_row_offset', 'damping_nm_s', 'torque_bias_nm', 'holdout']}), flush=True)
    primary, = [v for v in result['variants'] if v['primary']]
    checks = plan['reporting_checks']
    result['diagnostic_checks'] = {
        'condition_nrmse_pass': all(x <= checks['all_four_primary_condition_velocity_nrmse_max'] for x in primary['holdout']['condition_velocity_nrmse'].values()),
        'rmse_reduction_pass': primary['holdout']['rmse_reduction_fraction'] >= checks['primary_pooled_velocity_rmse_reduction_min'],
        'h4_acceptance_implied': False}
    result['source_drift'] = [p for p, h in hashes.items() if digest(p) != h]
    result['complete'] = True
    save()


if __name__ == '__main__':
    main()
