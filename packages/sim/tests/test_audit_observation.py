"""H2-01: invariant evidence must include steps between telemetry samples."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from strandbeest_sim import run
from strandbeest_sim.backend import FootLoad
from strandbeest_sim.backends.mujoco_backend import MujocoBackend
from strandbeest_sim.config import SimConfig
from strandbeest_sim.audit import audit_report
from strandbeest_sim.audit_observation import AuditObservation, _validator, observation_issues

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT/'contracts/sim-observation/cases.json').read_text())['cases']


def test_observation_schema_is_independent_of_windows_locale(monkeypatch):
    original = Path.read_text

    def read_as_system_locale(self, *args, **kwargs):
        if self.name == 'run.schema.json' and 'encoding' not in kwargs:
            return original(self, encoding='gbk')
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', read_as_system_locale)
    _validator.cache_clear()
    try:
        assert _validator().schema['$ref'] == '#/$defs/AuditObservation'
    finally:
        _validator.cache_clear()


def injected_run(monkeypatch, record_every):
    dt = .0005
    step = lambda be: round(be.time / dt)
    monkeypatch.setattr(MujocoBackend, 'max_penetration', lambda be: .006 if step(be) == 1 else 0.)
    monkeypatch.setattr(MujocoBackend, 'loop_residual', lambda be: .007 if step(be) == 2 else 0.)
    monkeypatch.setattr(MujocoBackend, 'foot_loads', lambda be: [
        FootLoad(0. if step(be) in (1, 2) else 1., 0., (0., 0., 0.), 0., (0., 0., 0.))
        for _ in be._foot_geoms])
    sc = SimConfig.model_validate({'solver': {'timestep': dt}, 'run': {
        'settle': 0, 'revolutions': 100, 'max_time': .01, 'frame_rate': 0, 'record_every': record_every}})
    return run(sc)


@pytest.mark.parametrize('metric,expected', [('max_loop_violation', .007), ('max_penetration', .006)])
def test_runner_catches_peak_between_logged_samples(monkeypatch, metric, expected):
    result = injected_run(monkeypatch, 20)
    assert result.metrics[metric] == expected


def test_runner_support_and_peaks_are_invariant_to_logging_cadence(monkeypatch):
    full = injected_run(monkeypatch, 1)
    sparse = injected_run(monkeypatch, 20)
    assert sparse.audit_observation == full.audit_observation
    assert sparse.audit_observation['airborne_steps'] == 2
    assert sparse.audit_observation['observed_steps'] == len(full.t)
    assert sparse.audit_observation['integration_steps'] == len(full.t)
    for name in full.series:
        np.testing.assert_array_equal(full.series[name][::20], sparse.series[name])


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_shared_observation_contract(case):
    counter = AuditObservation(case['timestep_s'], case['legs'], case['boundary'])
    for row in case['rows']:
        counter.observe(*row)
    result = counter.document(case['integration_steps'])
    assert result == case['expected']
    json.dumps(result, allow_nan=False)
    result['observed_steps'] = -100
    assert counter.document(case['integration_steps']) == case['expected']


def support_trace(airborne, record_every=1):
    sc = SimConfig.model_validate({'walker': {'legs': 4}, 'solver': {'timestep': .01},
                                  'run': {'record_every': record_every}})
    t = np.arange(20)*.01
    normal = np.zeros((20, 4))
    normal[:, 0] = 1
    normal[:airborne] = 0
    collector = AuditObservation(.01, 4, 'force_evaluation')
    for time_s, loads in zip(t, normal):
        collector.observe(time_s, loads, .005, .005)
    series = {'t': t[::record_every], 'foot_normal': normal[::record_every],
              'loop_residual': np.full(20, .005)[::record_every],
              'penetration': np.full(20, .005)[::record_every]}
    metrics = {'steady_window': 1, 'energy_residual_share': .02,
               'max_loop_violation': .005, 'max_penetration': .005, 'stride_per_rev': .2}
    return sc, metrics, series, collector.document(20)


@pytest.mark.parametrize('record_every', [1, 20, 37])
@pytest.mark.parametrize('airborne,failed', [(1, False), (2, True)])
def test_support_gate_uses_all_steps_with_unchanged_exact_boundary(record_every, airborne, failed):
    sc, metrics, series, observation = support_trace(airborne, record_every)
    assert observation_issues(sc, metrics, series, observation, 'mujoco') == []
    report = audit_report(sc, metrics, series, backend_name='mujoco', observation=observation)
    checks = [f['check'] for f in report['findings']]
    assert ('support' in checks) == failed
    assert not {'energy_closure', 'loop_closure', 'penetration'} & set(checks)
    # Missing gait evidence remains unknown even when numeric boundaries pass.
    assert not report['passed']
    if record_every > 1:
        assert 'support' in [f['check'] for f in report['legacy']['findings']]


@pytest.mark.parametrize('key,value', [
    ('integration_steps', 21), ('observed_steps', 19), ('observed_steps', True),
    ('invalid_steps', 1), ('time_gap_steps', 1), ('airborne_steps', 21), ('airborne_steps', 0),
    ('first_time_s', .01), ('last_time_s', .2), ('last_time_s', float('nan')),
    ('timestep_s', .02), ('legs', 6), ('boundary', 'post_step'), ('support_force_N', .01),
    ('max_loop_residual_m', .004), ('max_penetration_m', .004),
])
def test_incomplete_or_inconsistent_coverage_is_not_certified(key, value):
    sc, metrics, series, observation = support_trace(1)
    observation[key] = value
    assert observation_issues(sc, metrics, series, observation, 'mujoco')
    report = audit_report(sc, metrics, series, backend_name='mujoco', observation=observation)
    assert not report['passed']
    assert any(f['check'] == 'audit_evidence' and f['evidence'].get('metric') == 'audit_observation'
               for f in report['findings'])


def test_missing_coverage_does_not_reclassify_historical_sampled_support_failure():
    sc, metrics, series, _ = support_trace(1, 20)
    report = audit_report(sc, metrics, series, backend_name='mujoco')
    assert report['status'] == 'failed'
    assert 'support' in [f['check'] for f in report['findings']]


def test_nan_observation_is_retained_as_invalid_without_nonfinite_json():
    c = AuditObservation(.01, 4, 'force_evaluation')
    c.observe(0., [1., 0., 0., 0.], float('nan'), 0.)
    d = c.document(1)
    assert d['invalid_steps'] == 1 and d['max_loop_residual_m'] is None
    json.dumps(d, allow_nan=False)


def test_forged_peak_cannot_hide_a_violation_present_in_raw_samples():
    sc, metrics, series, observation = support_trace(1)
    series['penetration'][3] = .006
    assert 'recorded_max_penetration_m_disagrees' in observation_issues(sc, metrics, series, observation)


def test_observation_validation_is_read_only():
    sc, metrics, series, observation = support_trace(1)
    before = copy.deepcopy(observation)
    assert observation_issues(sc, metrics, series, observation) == []
    assert observation == before
