"""Streaming invariant evidence over driven integration steps (Run contract).

Telemetry decimation never enters this accumulator. It does not aggregate gait
or energy windows and cannot establish physical or geometric applicability.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from numbers import Real

import numpy as np
from jsonschema import Draft202012Validator

from strandbeest_common.schemas import schema_dir

SUPPORT_FORCE_N = 1e-6
ROUND_OFF = 128 * np.finfo(float).eps


def finite(value):
    try:
        return isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(value)
    except OverflowError:
        return False


class AuditObservation:
    def __init__(self, timestep_s: float, legs: int, boundary: str):
        if not finite(timestep_s) or timestep_s <= 0 or not isinstance(legs, int) or legs < 1:
            raise ValueError('Audit observations require a positive timestep and leg count')
        if boundary not in ('force_evaluation', 'post_step'):
            raise ValueError('Unknown observation boundary')
        self.value = dict(version=1, scope='driven_steps_excluding_settle', boundary=boundary,
                          timestep_s=float(timestep_s), legs=legs, support_force_N=SUPPORT_FORCE_N,
                          observed_steps=0, invalid_steps=0, time_gap_steps=0, airborne_steps=0,
                          first_time_s=None, last_time_s=None,
                          max_loop_residual_m=None, max_penetration_m=None)

    def observe(self, time_s, normal, loop_residual_m, penetration_m):
        v = self.value
        v['observed_steps'] += 1
        valid_time = finite(time_s) and time_s >= 0
        if valid_time:
            previous = v['last_time_s']
            expected = (0. if v['boundary'] == 'force_evaluation' else v['timestep_s']) if previous is None else previous + v['timestep_s']
            if abs(time_s - expected) > ROUND_OFF * max(abs(time_s), abs(expected), v['timestep_s']):
                v['time_gap_steps'] += 1
            if v['first_time_s'] is None:
                v['first_time_s'] = float(time_s)
            v['last_time_s'] = float(time_s)
        try:
            loads = list(normal)
            valid_loads = len(loads) == v['legs'] and all(finite(f) and f >= 0 for f in loads)
        except TypeError:
            valid_loads = False
        if valid_loads and not any(f > SUPPORT_FORCE_N for f in loads):
            v['airborne_steps'] += 1
        valid = valid_time and valid_loads
        for name, value in [('max_loop_residual_m', loop_residual_m), ('max_penetration_m', penetration_m)]:
            if finite(value) and value >= 0:
                v[name] = float(value) if v[name] is None else max(v[name], float(value))
            else:
                valid = False
        if not valid:
            v['invalid_steps'] += 1

    def document(self, integration_steps: int) -> dict:
        return {**self.value, 'integration_steps': integration_steps}


@lru_cache(maxsize=1)
def _validator():
    schema = json.loads((schema_dir() / 'run.schema.json').read_text())
    return Draft202012Validator({'$ref': '#/$defs/AuditObservation', '$defs': schema['$defs']})


def observation_issues(sc, metrics, series, observation, backend_name=None):
    """Check coverage, Scenario identity and contradictions in recorded samples.

    Historical sparse traces cannot reconstruct missing steps. No flag supplied
    by the caller is sufficient to claim coverage; counts and evidence must fit.
    """
    if observation is None:
        return ['missing_all_step_observation']
    if not isinstance(observation, dict) or list(_validator().iter_errors(observation)):
        return ['invalid_observation_contract']
    o = observation
    if any(isinstance(v, Real) and not finite(v) for v in o.values()):
        return ['nonfinite_observation']
    issues = []
    n = o['integration_steps']
    if not n or o['observed_steps'] != n or o['invalid_steps'] or o['time_gap_steps'] or o['airborne_steps'] > n:
        issues.append('incomplete_or_invalid_steps')
    if o['legs'] != sc.walker.legs or o['timestep_s'] != sc.solver.timestep:
        issues.append('scenario_mismatch')
    boundary = {'mujoco': 'force_evaluation', 'k2': 'post_step'}.get(backend_name)
    if boundary is not None and o['boundary'] != boundary:
        issues.append('backend_boundary_mismatch')
    first, last, dt = o['first_time_s'], o['last_time_s'], o['timestep_s']
    expected_first = 0. if o['boundary'] == 'force_evaluation' else dt
    if not finite(first) or not finite(last):
        issues.append('missing_observation_times')
    else:
        # n-dependent bound covers accumulation of floating-point timestamps.
        bound = ROUND_OFF * max(n, 1) * max(abs(last), dt)
        if first != expected_first or last < first or abs(last - first - (n - 1)*dt) > bound:
            issues.append('inconsistent_observation_times')
    for key, metric in [('max_loop_residual_m', 'max_loop_violation'), ('max_penetration_m', 'max_penetration')]:
        if not finite(o[key]) or not finite(metrics.get(metric)) or metrics[metric] != o[key]:
            issues.append('inconsistent_' + metric)
    if issues:
        return issues
    if series is None:
        return []
    try:
        t = np.asarray(series['t'])
        normal = np.asarray(series['foot_normal'])
        loop = np.asarray(series['loop_residual'])
        penetration = np.asarray(series['penetration'])
        count = (n + sc.run.record_every - 1) // sc.run.record_every
        if (t.shape != (count,) or loop.shape != t.shape or penetration.shape != t.shape
                or normal.shape != (count, sc.walker.legs)
                or any(not np.issubdtype(a.dtype, np.number) or np.iscomplexobj(a) or not np.isfinite(a).all()
                       for a in (t, normal, loop, penetration)) or np.any(normal < 0) or np.any(loop < 0)):
            return ['invalid_or_incomplete_recorded_samples']
        expected_t = first + np.arange(count)*sc.run.record_every*dt
        if np.any(np.abs(t-expected_t) > bound) or (count > 1 and np.any(np.diff(t) <= 0)):
            issues.append('recorded_times_disagree')
        sparse_airborne = int(np.count_nonzero(np.all(normal <= SUPPORT_FORCE_N, axis=1)))
        if sparse_airborne > o['airborne_steps'] or count-sparse_airborne > n-o['airborne_steps']:
            issues.append('recorded_support_disagrees')
        for a, key in [(loop, 'max_loop_residual_m'), (penetration, 'max_penetration_m')]:
            observed_max = max(0., float(np.max(a)))
            if observed_max > o[key] or (sc.run.record_every == 1 and observed_max != o[key]):
                issues.append('recorded_' + key + '_disagrees')
        if sc.run.record_every == 1 and sparse_airborne != o['airborne_steps']:
            issues.append('full_support_disagrees')
    except (KeyError, TypeError, ValueError):
        issues.append('missing_or_invalid_recorded_samples')
    return issues
