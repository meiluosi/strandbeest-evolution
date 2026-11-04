"""Recorded iteration budget, residual diagnostics and original K2 cohort."""
import argparse
import hashlib
import json
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from strandbeest_sim.backends.k2_backend import K2Backend


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ObservedK2(K2Backend):
    def __init__(self, detailed=False):
        super().__init__()
        self.detailed = detailed
        self.iterations_seen = Counter()
        self.contact_diagnostics = []
        self.frozen = {}
        self.maxima = [-1., -1., -1., -1.]

    def _step_once(self):
        if not self.detailed:
            super()._step_once()
            self.iterations_seen[self._last_contact_iterations] += 1
            return
        assert self._kind == 'walker' and self._contact_softness is None
        dt, q, velocity = self.timestep, self._q.copy(), self._v.copy()
        sample = self._mass_terms()
        matrix = sample.matrix.copy()
        damping = float(self._inertia.joint_damping @ sample.joint_ratios**2)+self._damping
        effective = matrix.copy()
        effective[3, 3] += dt*damping
        allowed = [0, 1, 3] if self._pitch_locked else [0, 1, 2, 3]
        inverse = np.zeros((4, 4))
        inverse[np.ix_(allowed, allowed)] = np.linalg.inv(effective[np.ix_(allowed, allowed)])
        normals, tangents, penetrations, legs = [], [], [], []
        for leg in range(self._n_legs):
            center, jn, jt = self._foot_contact_kinematics(leg)
            penetration = self._foot_radius-center[1]
            if penetration > 0:
                legs.append(leg)
                normals.append(jn)
                tangents.append(jt)
                penetrations.append(penetration)
        load = sum(l.normal for l in self._last_foot_loads) if self._last_foot_loads else self._m_total*abs(self._gravity[2])
        friction = float(self._inertia.joint_friction @ np.abs(sample.joint_ratios))+self._frictionloss
        friction += self._joint_friction_coeff*self._joint_pin_radius*load
        friction = np.copysign(friction, velocity[3]) if abs(velocity[3]) > 1e-7 else 0.
        torque = -self._direction*self._applied_joint_torque if self._actuator_released else 0.
        force = sample.gravity(self._gravity)-sample.bias(velocity)+np.array([self._applied_tx_force, 0., 0., torque-friction])
        free_velocity = inverse @ (matrix @ velocity+dt*force)
        desired = -self._direction*self._kp*(self._actuator_target-self._q0+self._direction*q[3])*dt
        motor_limit = None if self._max_torque is None else self._max_torque*dt
        super()._step_once()
        self.iterations_seen[self._last_contact_iterations] += 1
        normal_error = tangent_error = 0.
        pn, pt = [], []
        for leg, jn, jt, penetration in zip(legs, normals, tangents, penetrations):
            n = self._last_foot_loads[leg].normal*dt
            t = self._last_foot_loads[leg].force[0]*dt
            pn.append(n)
            pt.append(t)
            wn, wt = float(jn @ inverse @ jn), float(jt @ inverse @ jt)
            residual = float(jn @ self._v)-.15*penetration/dt
            normal_error = max(normal_error, wn*abs(n-max(0., n-residual/wn)))
            projected = np.clip(t-float(jt @ self._v)/wt, -self._foot_friction*n, self._foot_friction*n)
            tangent_error = max(tangent_error, wt*abs(t-projected))
        motor_impulse = -self._direction*self._last_actuator_force*dt
        expected_motor = 0. if self._actuator_released else desired-self._kv*dt*self._v[3]
        if motor_limit is not None and not self._actuator_released:
            expected_motor = float(np.clip(expected_motor, -motor_limit, motor_limit))
        motor_error = abs(motor_impulse-expected_motor)
        values = [normal_error, tangent_error, motor_error, len(legs)]
        self.contact_diagnostics.append([self.time, q[3], self._last_contact_iterations, len(legs), *values[:3]])
        for key, value in enumerate(values):
            if value > self.maxima[key]:
                self.maxima[key] = value
                self.frozen[str(key)] = {
                    'time': self.time, 'q_before': q.tolist(), 'v_before': velocity.tolist(),
                    'mass': matrix.tolist(), 'effective_inverse': inverse.tolist(),
                    'free_velocity': free_velocity.tolist(), 'normal_jacobians': [v.tolist() for v in normals],
                    'tangent_jacobians': [v.tolist() for v in tangents], 'penetrations': penetrations,
                    'legs': legs, 'mu': self._foot_friction, 'dt': dt, 'beta': .15,
                    'motor_released': self._actuator_released, 'motor_desired_impulse': desired,
                    'motor_damping_dt': self._kv*dt, 'motor_impulse_limit': motor_limit,
                    'observed_velocity': self._v.tolist(), 'observed_normal_impulses': pn,
                    'observed_tangent_impulses': pt, 'observed_motor_impulse': motor_impulse,
                    'normal_residual_m_s': normal_error, 'tangent_residual_m_s': tangent_error,
                    'motor_law_residual_N_m_s': motor_error, 'iterations': self._last_contact_iterations,
                }


def trial(task):
    from strandbeest_sim.audit import audit_report
    from strandbeest_sim.config import sim_config
    from strandbeest_sim.runner import run
    case, scenario, settings, output, detailed = task
    started = time.perf_counter()
    sc = sim_config(scenario)
    sc.solver.timestep, sc.run.max_time = settings['timestep_s'], settings['max_time_s']
    try:
        be = ObservedK2(detailed)
        result = run(sc, backend=be)
        path = Path(output)/f'case{case}.npz'
        assert not path.exists()
        arrays = {'t': result.t, 'psi': result.psi, 'x': result.x, 'z': result.z,
                  'torque': result.torque, **result.series}
        np.savez_compressed(path, **arrays)
        row = {'case': case, 'completed': True, 'scenario': sc.model_dump(mode='json'),
               'actual_timestep': be.timestep, 'configured_iteration_budget': be._contact_iterations,
               'iterations_histogram': dict(sorted(be.iterations_seen.items())),
               'wall_s': time.perf_counter()-started, 'metrics': result.metrics, 'stalled': result.stalled,
               'audit': audit_report(sc, result.metrics, arrays, result.stalled, backend_name='k2'),
               'simulated_s': float(result.t[-1]), 'arrays_path': str(path), 'arrays_sha256': digest(path)}
        if detailed:
            path = Path(output)/f'contact-case{case}.npz'
            assert not path.exists()
            np.savez_compressed(path, diagnostics=np.array(be.contact_diagnostics))
            row.update(contact_arrays_path=str(path), contact_arrays_sha256=digest(path),
                       contact_columns=['time_s', 'phase_rad', 'iterations', 'active_contacts',
                                        'normal_residual_m_s', 'tangent_residual_m_s', 'motor_law_residual_N_m_s'],
                       contact_maxima=be.maxima, frozen_states=be.frozen)
        return row
    except Exception as exc:
        row = {'case': case, 'completed': False, 'scenario': sc.model_dump(mode='json'),
               'wall_s': time.perf_counter()-started, 'error': traceback.format_exc()}
        if hasattr(exc, 'solution'):
            from dataclasses import asdict

            def serializable(value):
                if isinstance(value, np.ndarray):
                    return value.tolist()
                if isinstance(value, dict):
                    return {k: serializable(v) for k, v in value.items()}
                if isinstance(value, (list, tuple)):
                    return [serializable(v) for v in value]
                return value.item() if isinstance(value, np.generic) else value

            row['failed_contact_system'] = serializable(exc.system)
            row['failed_contact_solution'] = serializable(asdict(exc.solution))
            row['time_before_failed_step'] = be.time
            row['iterations_histogram'] = dict(sorted(be.iterations_seen.items()))
        return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True, choices=['diagnostic', 'coarse', 'cohort'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--plan', type=Path, default=Path('experiments/hardening-k2-contact-solve-plan-2026-11-04.json'))
    args = parser.parse_args()
    assert not args.output.exists()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plan_path = args.plan
    plan = json.loads(plan_path.read_text())
    assert digest(plan['source_path']) == plan['source_sha256']
    original = json.loads(Path(plan['source_path']).read_text())
    assert original['seed'] == plan['seed'] == 1 and len(original['rows']) == 64
    cases = plan['original_cases'] if args.stage == 'cohort' else plan['diagnostic_cases']
    paths = list(Path('packages/sim/src').rglob('*.py'))+list(Path('packages/common/src').rglob('*.py'))
    paths += list(Path('schemas').glob('*.schema.json'))+[Path(__file__)]
    sources = {str(p): digest(p) for p in sorted(paths)}
    result = {'complete': False, 'stage': args.stage, 'plan_path': str(plan_path),
              'plan_sha256': digest(plan_path), 'source_sha256': sources,
              'h2_01_accepted': False, 'independent_validation_accepted': False,
              'physical_evidence_upgraded': False, 'rows': []}

    def save():
        result['rows'].sort(key=lambda row: row['case'])
        tmp = args.output.with_suffix('.partial')
        tmp.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
        tmp.replace(args.output)

    save()
    tasks = [(c, original['rows'][c]['scenario'], plan['stages'][args.stage], str(args.output.parent),
              args.stage != 'cohort') for c in cases]
    with ProcessPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(trial, t) for t in tasks]):
            row = future.result()
            result['rows'].append(row)
            save()
            print(json.dumps({'case': row['case'], 'completed': row['completed'], 'wall_s': row['wall_s'],
                              'stride': row.get('metrics', {}).get('stride_per_rev'),
                              'energy_residual': row.get('metrics', {}).get('energy_residual_share'),
                              'contact_maxima': row.get('contact_maxima')}), flush=True)
    result['source_drift'] = [p for p, h in sources.items() if digest(p) != h]
    assert not result['source_drift']
    result['complete'] = len(result['rows']) == len(cases)
    result['execution_errors'] = sum(not row['completed'] for row in result['rows'])
    save()


if __name__ == '__main__':
    main()
