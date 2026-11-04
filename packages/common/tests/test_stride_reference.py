"""Real Python binding against the pre-existing endpoint/angle study.

These are geometric-model checks, never substitutes for physical validation.
The Rust module separately checks an independent closed-form ellipse integral.
"""
import copy
import json
import math
from pathlib import Path

import pytest

from strandbeest_common import load_spec, stride_reference

ROOT = Path(__file__).resolve().parents[3]
CORPUS = json.loads((ROOT / 'contracts/stride-reference/cases.json').read_text())


@pytest.mark.parametrize('row', CORPUS['cases'], ids=lambda row: row['name'])
def test_native_matches_independent_geometry_study(row):
    result = stride_reference(load_spec(row['spec']), **row['options'])
    assert result['status'] == 'estimated'
    for key, value in row['expected'].items():
        assert result['estimate'][key] == pytest.approx(value, abs=CORPUS['tolerance_m'], rel=0)


def test_reverse_scale_point_limit_and_native_handle_invalidation():
    row = copy.deepcopy(CORPUS['cases'][0])
    spec, options = load_spec(row['spec']), row['options']
    initial = stride_reference(spec, **options)['estimate']
    reversed_ = stride_reference(spec, **{**options, 'direction': -options['direction']})['estimate']
    scaled = stride_reference(spec, **{**options, 'unit_m': options['unit_m'] * 3,
                                      'radius_m': options['radius_m'] * 3})['estimate']
    point = stride_reference(spec, **{**options, 'radius_m': 0})['estimate']
    shifted = stride_reference(spec, **{**options, 'phases_rad': [p + .123 for p in options['phases_rad']]})['estimate']
    for key in row['expected']:
        assert reversed_[key] == -initial[key]
        assert scaled[key] == pytest.approx(3 * initial[key], rel=1e-12, abs=1e-15)
        assert shifted[key] == pytest.approx(initial[key], rel=0, abs=1e-12)
    assert point['rolling_m_per_rev'] == 0
    assert point['contact_stride_m_per_rev'] == initial['point_stride_m_per_rev']
    spec.params['a'] *= 1.01
    changed = stride_reference(spec, **options)['estimate']
    assert abs(changed['contact_stride_m_per_rev'] - initial['contact_stride_m_per_rev']) > 1e-6


@pytest.mark.parametrize('change', [
    {'phases_rad': []}, {'phases_rad': [math.nan]}, {'direction': 0},
    {'radius_m': -1}, {'unit_m': 0}, {'unit_m': math.inf},
    {'brackets': 1.5}, {'brackets': -1}, {'brackets': 1_000_001}, {'owner_start': 'G'},
])
def test_invalid_inputs_are_errors_not_zero_stride(change):
    row = CORPUS['cases'][0]
    with pytest.raises(ValueError):
        stride_reference(load_spec(row['spec']), **{**row['options'], **change})


def test_nonassembly_is_explicit_and_missing_native_capability_never_falls_back(monkeypatch):
    row = copy.deepcopy(CORPUS['cases'][0])
    row['spec']['params']['b'] = 1e-8
    result = stride_reference(load_spec(row['spec']), **row['options'])
    assert result['status'] == 'unassembled'
    assert result['estimate'] is None
    import strandbeest_common.stride as adapter
    monkeypatch.setattr(adapter, '_kernel', lambda spec: object())
    with pytest.raises(AttributeError, match='stride_reference_json'):
        stride_reference(load_spec(CORPUS['cases'][0]['spec']), **row['options'])


def test_actual_owner_changes_rolling_for_a_nontriangular_foot():
    spec = load_spec(json.loads((ROOT / 'contracts/kinematics/fourbar-crank-rocker.json').read_text())['spec'])
    options = dict(owner_start='G', phases_rad=[math.tau * i / 6 for i in range(6)],
                   direction=-1, unit_m=.002, radius_m=.002, brackets=720)
    ground_bar = stride_reference(spec, **options)['estimate']
    crank_bar = stride_reference(spec, **{**options, 'owner_start': 'C'})['estimate']
    assert ground_bar['point_stride_m_per_rev'] == crank_bar['point_stride_m_per_rev']
    assert abs(ground_bar['rolling_m_per_rev'] - crank_bar['rolling_m_per_rev']) > 1e-5
