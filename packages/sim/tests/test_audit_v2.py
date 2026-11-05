"""ADR-0012: a computable geometric estimate is not evidence of applicability."""
import copy
import json

import numpy as np
import pytest

from strandbeest_common import Design, solve_pose
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design
from strandbeest_sim.config import sim_config
from strandbeest_sim.builder import resolve_spec
from strandbeest_sim.audit import audit_report, reference_for_scenario
from strandbeest_sim.audit_observation import AuditObservation
from strandbeest_sim.skeptic import audit, audit_legacy


@pytest.fixture
def controlled():
    design = Design(json.loads((schema_dir() / 'examples/design-jansen-small-6leg.json').read_text()))
    sc = sim_config(scenario_from_design(design, {'solver': {'timestep': .01}, 'run': {'record_every': 1}}))
    nominal = reference_for_scenario(sc)['signed_stride_m_per_rev']
    t = np.arange(701) * .01
    theta = sc.walker.direction*2*t
    spec = resolve_spec(sc)
    normal = np.zeros((len(t), sc.walker.legs))
    for i, angle in enumerate(theta):
        leg = min(range(sc.walker.legs), key=lambda k: solve_pose(spec, angle+2*np.pi*k/sc.walker.legs)[spec.foot][1])
        normal[i, leg] = 1
    series = {'t': t, 'psi': 2*t, 'theta_rad': theta, 'x': nominal*2*t/(2*np.pi),
              'foot_normal': normal,
              'foot_slip': np.zeros((len(t), sc.walker.legs)),
              'loop_residual': np.zeros(len(t)), 'penetration': np.zeros(len(t))}
    metrics = {'steady_window': 1., 'energy_residual_share': 0.,
               'max_loop_violation': 0., 'max_penetration': 0., 'stride_per_rev': nominal}
    observation = AuditObservation(sc.solver.timestep, sc.walker.legs, 'force_evaluation')
    for time_s, loads in zip(t, normal):
        observation.observe(time_s, loads, 0., 0.)
    return sc, metrics, series, observation.document(len(t))


def report(controlled):
    sc, metrics, series, observation = controlled
    return audit_report(sc, metrics, series, backend_name='mujoco', observation=observation)


def test_controlled_exact_constraint_trace_has_a_scoped_pass_and_legacy_record(controlled):
    value = report(controlled)
    assert value['version'] == 2 and value['status'] == 'passed'
    assert value['passed'] and value['findings'] == []
    assert value['legacy']['version'] == 1
    assert not value['physical_validation_implied']
    assert value['stride_reference']['applicability'] == 'verified'


@pytest.mark.parametrize('key', ['foot_normal', 'foot_slip', 'loop_residual', 'penetration', 't', 'psi', 'x', 'theta_rad'])
def test_missing_applicability_input_cannot_be_a_pass(controlled, key):
    del controlled[2][key]
    value = report(controlled)
    assert not value['passed'] and value['status'] == 'unverified'
    assert any(f['check'] in ('stride_reference_unverified', 'audit_evidence') for f in value['findings'])


@pytest.mark.parametrize('key,value', [('foot_slip', 1e-12), ('loop_residual', 1e-12), ('penetration', 1e-12)])
def test_nonzero_physical_deviations_are_not_hidden_in_a_numerical_tolerance(controlled, key, value):
    controlled[2][key][10] = value
    assert report(controlled)['status'] == 'unverified'


def test_flight_and_decimated_telemetry_do_not_certify_lowest_foot_support(controlled):
    controlled[2]['foot_normal'][20] = 0
    assert report(controlled)['status'] == 'unverified'
    controlled[2]['foot_normal'][20] = 1
    controlled[0].run.record_every = 20
    assert report(controlled)['status'] == 'unverified'


@pytest.mark.parametrize('change', ['slope', 'pitch', 'stalled', 'unknown_backend'])
def test_outside_reference_scope_requires_independent_validation(controlled, change):
    sc, metrics, series, observation = controlled
    if change == 'slope': sc.terrain.kind = 'slope'
    if change == 'pitch': sc.walker.pitch = 'free'
    value = audit_report(sc, metrics, series, stalled=change == 'stalled',
                         backend_name=None if change == 'unknown_backend' else 'mujoco', observation=observation)
    assert value['status'] == 'unverified' and not value['passed']


def test_sign_is_preserved_and_opposite_motion_fails_without_absolute_value_rescue(controlled):
    sc, metrics, series, _ = controlled
    sc.walker.direction *= -1
    series['theta_rad'] *= -1
    spec = resolve_spec(sc)
    series['foot_normal'][:] = 0
    for i, angle in enumerate(series['theta_rad']):
        leg = min(range(sc.walker.legs), key=lambda k: solve_pose(spec, angle+2*np.pi*k/sc.walker.legs)[spec.foot][1])
        series['foot_normal'][i, leg] = 1
    expected = reference_for_scenario(sc)['signed_stride_m_per_rev']
    assert expected == -metrics['stride_per_rev']
    # Actual trace initially keeps the wrong sign.
    assert report(controlled)['status'] == 'failed'
    metrics['stride_per_rev'] = expected
    series['x'] *= -1
    assert report(controlled)['status'] == 'passed'


def test_incompatible_elevated_supports_cannot_certify_a_zero_slip_table(controlled):
    controlled[2]['foot_normal'][:] = 1
    value = report(controlled)
    assert value['status'] == 'unverified'
    assert any(c['code'] == 'loaded_feet_are_lowest' and c['status'] == 'unverified'
               for c in value['stride_reference']['conditions'])


def test_reference_cache_tracks_file_contents_and_does_not_share_mutable_outputs(controlled, tmp_path):
    sc = controlled[0]
    source = tmp_path / 'spec.json'
    doc = copy.deepcopy(sc.linkage.spec)
    source.write_text(json.dumps(doc))
    sc.linkage.spec = str(source)
    initial = reference_for_scenario(sc)
    initial['signed_stride_m_per_rev'] = 99
    assert reference_for_scenario(sc)['signed_stride_m_per_rev'] != 99
    before = reference_for_scenario(sc)['signed_stride_m_per_rev']
    doc['params']['a'] *= 1.01
    source.write_text(json.dumps(doc))
    assert reference_for_scenario(sc)['signed_stride_m_per_rev'] != before


@pytest.mark.parametrize('key,value,code', [('energy_residual_share', .021, 'energy_closure'),
    ('max_loop_violation', .0051, 'loop_closure'), ('max_penetration', .0051, 'penetration')])
def test_original_numeric_thresholds_still_fail_even_when_stride_is_unverified(controlled, key, value, code):
    controlled[1][key] = value
    controlled[0].run.record_every = 20
    value = report(controlled)
    assert value['status'] == 'failed'
    assert code in [f['check'] for f in value['findings']]


def test_legacy_result_is_preserved_exactly_and_new_default_does_not_claim_trust(controlled):
    from dataclasses import asdict
    sc, metrics, series, _ = controlled
    sc.run.record_every = 20
    value = report(controlled)
    assert value['legacy']['findings'] == [asdict(f) for f in audit_legacy(sc, metrics, series)]
    assert audit(sc, metrics, series, backend_name='mujoco')


def test_run_contract_accepts_report_and_rejects_pass_with_unverified_conditions(controlled):
    from jsonschema import Draft202012Validator
    schema = json.loads((schema_dir() / 'run.schema.json').read_text())
    validator = Draft202012Validator({'$ref': '#/$defs/SimulationAudit', '$defs': schema['$defs']})
    value = report(controlled)
    validator.validate(value)
    value['stride_reference']['applicability'] = 'unverified'
    assert list(validator.iter_errors(value))


def test_audit_is_read_only_and_serializable(controlled):
    before = copy.deepcopy(controlled)
    value = report(controlled)
    json.dumps(value, allow_nan=False)
    assert controlled[0] == before[0] and controlled[1] == before[1]
    for key in controlled[2]: np.testing.assert_array_equal(controlled[2][key], before[2][key])
    assert controlled[3] == before[3]


def test_independent_validation_verifies_nonapplicable_run_and_passes(controlled):
    from jsonschema import Draft202012Validator
    sc, metrics, series, observation = controlled
    # Make geometric reference unverified (e.g. slope terrain)
    sc.terrain.kind = 'slope'
    stride = float(metrics['stride_per_rev'])
    counterpart = {
        'backend': 'k2',
        'stride_per_rev': stride * 1.02,  # 2% difference, well within 15%
        'stalled': False,
        'steady_window': 1.0,
        'energy_residual_share': 0.001,
        'max_loop_violation': 0.0001,
        'max_penetration': 0.0001,
        'provenance': {'study': 'test_independent'}
    }
    value = audit_report(sc, metrics, series, backend_name='mujoco',
                         observation=observation, independent_validation=counterpart)
    assert value['version'] == 2 and value['status'] == 'passed'
    assert value['passed'] is True
    assert value['findings'] == []
    assert value['stride_reference']['applicability'] == 'unverified'
    assert value['stride_reference']['independent_validation']['status'] == 'verified'
    assert value['independent_validation']['status'] == 'verified'
    assert abs(value['independent_validation']['relative_difference'] - 0.02) < 1e-6

    # Verify JSON schema accepts the passed report with independent_validation
    schema = json.loads((schema_dir() / 'run.schema.json').read_text())
    validator = Draft202012Validator({'$ref': '#/$defs/SimulationAudit', '$defs': schema['$defs']})
    validator.validate(value)


def test_independent_validation_rejects_same_backend(controlled):
    sc, metrics, series, observation = controlled
    sc.terrain.kind = 'slope'
    counterpart = {
        'backend': 'mujoco',  # Same backend!
        'stride_per_rev': float(metrics['stride_per_rev']),
        'stalled': False,
        'steady_window': 1.0,
        'energy_residual_share': 0.0,
        'max_loop_violation': 0.0,
        'max_penetration': 0.0,
    }
    value = audit_report(sc, metrics, series, backend_name='mujoco',
                         observation=observation, independent_validation=counterpart)
    assert value['status'] == 'failed'
    assert any(f['check'] == 'independent_validation_invalid' for f in value['findings'])


def test_independent_validation_rejects_counterpart_invariant_failures(controlled):
    sc, metrics, series, observation = controlled
    sc.terrain.kind = 'slope'
    # Test stalled counterpart
    stalled_cp = {
        'backend': 'k2',
        'stride_per_rev': float(metrics['stride_per_rev']),
        'stalled': True,
        'steady_window': 1.0,
    }
    v_stalled = audit_report(sc, metrics, series, backend_name='mujoco',
                             observation=observation, independent_validation=stalled_cp)
    assert v_stalled['status'] == 'failed'
    assert any(f['check'] == 'independent_validation_invalid' for f in v_stalled['findings'])

    # Test excess energy residual
    leaky_cp = {
        'backend': 'k2',
        'stride_per_rev': float(metrics['stride_per_rev']),
        'stalled': False,
        'steady_window': 1.0,
        'energy_residual_share': 0.05,  # > 0.02 limit
    }
    v_leaky = audit_report(sc, metrics, series, backend_name='mujoco',
                           observation=observation, independent_validation=leaky_cp)
    assert v_leaky['status'] == 'failed'
    assert any(f['check'] == 'independent_validation_invalid' for f in v_leaky['findings'])


def test_independent_validation_rejects_stride_difference_over_tolerance(controlled):
    sc, metrics, series, observation = controlled
    sc.terrain.kind = 'slope'
    stride = float(metrics['stride_per_rev'])
    counterpart = {
        'backend': 'k2',
        'stride_per_rev': stride * 1.25,  # 25% difference > 15%
        'stalled': False,
        'steady_window': 1.0,
        'energy_residual_share': 0.0,
        'max_loop_violation': 0.0,
        'max_penetration': 0.0,
    }
    value = audit_report(sc, metrics, series, backend_name='mujoco',
                         observation=observation, independent_validation=counterpart)
    assert value['status'] == 'failed'
    assert any(f['check'] == 'stride_vs_independent_validation' for f in value['findings'])
