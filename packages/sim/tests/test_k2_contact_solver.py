import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from k2_contact_reference import enumerate_contact_modes
from strandbeest_sim.backends.k2_contact import ContactConvergenceError, solve_contacts
from test_k2_work import body

CASES = json.loads((Path(__file__).parent/'fixtures/k2-contact-coupled.json').read_text())['rows']


def arguments(system, iterations=100):
    return dict(free_velocity=np.array(system['free_velocity']), inverse_mass=np.array(system['effective_inverse']),
                normals=system['normal_jacobians'], tangents=system['tangent_jacobians'],
                targets=system['beta']*np.array(system['penetrations'])/system['dt'],
                normal_compliance=np.zeros(len(system['legs'])), friction=system['mu'],
                motor_enabled=not system['motor_released'], motor_desired=system['motor_desired_impulse'],
                motor_damping_dt=system['motor_damping_dt'], motor_limit=system['motor_impulse_limit'],
                iterations=iterations)


@pytest.mark.parametrize('case', CASES, ids=lambda r: f"case{r['case']}-peak{r['key']}")
def test_known_pgs_failures_match_independent_simultaneous_contact_modes(case):
    reference = enumerate_contact_modes(case['system'])
    assert len(reference) == 1
    result = solve_contacts(**arguments(case['system']))
    assert result.converged and result.iterations <= 100
    np.testing.assert_allclose(result.velocity, reference[0]['velocity'], rtol=1e-11, atol=1e-12)
    assert np.all(result.normal >= 0)
    assert np.all(np.abs(result.tangent) <= case['system']['mu']*result.normal)


def test_insufficient_budget_is_reported_as_unconverged():
    case = next(r for r in CASES if r['case'] == 61 and r['key'] == '1')
    short = solve_contacts(**arguments(case['system'], iterations=1))
    complete = solve_contacts(**arguments(case['system']))
    assert not short.converged and short.iterations == 1
    assert complete.converged
    assert max(short.normal_error, short.tangent_error) > 1e-6
    assert max(complete.normal_error, complete.tangent_error) < 1e-12


def test_backend_rejects_unconverged_step_without_advancing_position_or_time(monkeypatch):
    import strandbeest_sim.backends.k2_backend as module
    actual = module.solve_contacts

    def unresolved(**kwargs):
        return replace(actual(**kwargs), converged=False, normal_error=.1)

    monkeypatch.setattr(module, 'solve_contacts', unresolved)
    _, be, _ = body()
    q, v, time = be._q.copy(), be._v.copy(), be.time
    with pytest.raises(ContactConvergenceError) as raised:
        be.step()
    assert not raised.value.solution.converged
    np.testing.assert_array_equal(be._q, q)
    np.testing.assert_array_equal(be._v, v)
    assert be.time == time


def test_soft_normal_compliance_enters_the_simultaneous_equations():
    mass, target, compliance = 2., .1, .5
    result = solve_contacts(free_velocity=np.array([0., -1., 0., 0.]),
                            inverse_mass=np.diag([1/mass, 1/mass, 1., 1.]),
                            normals=[[0., 1., 0., 0.]], tangents=[[1., 0., 0., 0.]],
                            targets=[target], normal_compliance=[compliance], friction=.5,
                            motor_enabled=False, motor_desired=0., motor_damping_dt=0.,
                            motor_limit=None, iterations=100)
    impulse = (target+1)/(1/mass+compliance)
    assert result.converged
    assert result.normal[0] == pytest.approx(impulse, abs=1e-14)
    assert result.velocity[1] == pytest.approx(-1+impulse/mass, abs=1e-14)
