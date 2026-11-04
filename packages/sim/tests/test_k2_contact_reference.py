"""Check the diagnostic mode enumerator against closed-form elementary systems."""
import numpy as np
import pytest

from k2_contact_reference import enumerate_contact_modes


def system(*, velocity=(0., -1., 0., 0.), mu=.5, mass=2.):
    return {'normal_jacobians': [[0., 1., 0., 0.]], 'tangent_jacobians': [[1., 0., 0., 0.]],
            'effective_inverse': np.diag([1/mass, 1/mass, 1., 1.]).tolist(),
            'free_velocity': list(velocity), 'penetrations': [0.], 'beta': .15, 'dt': .01,
            'mu': mu, 'motor_released': True, 'motor_impulse_limit': None,
            'motor_desired_impulse': 0., 'motor_damping_dt': 0.}


@pytest.mark.parametrize('vx,vz', [(.2, -1.), (2., -1.), (-2., -1.), (.3, 1.)])
def test_mode_enumeration_matches_sticking_sliding_and_separation(vx, vz):
    data = system(velocity=(vx, vz, 0., 0.))
    expected = [np.sign(vx)*max(0., abs(vx)-.5*max(0., -vz)), max(0., vz), 0., 0.]
    solutions = enumerate_contact_modes(data)
    assert solutions
    for result in solutions:
        np.testing.assert_allclose(result['velocity'], expected, rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize('initial', [-2., 2.])
@pytest.mark.parametrize('limit', [None, .01])
def test_mode_enumeration_matches_bounded_implicit_free_motor(initial, limit):
    data = system(velocity=(0., 0., 0., initial))
    data.update(normal_jacobians=[], tangent_jacobians=[], penetrations=[],
                motor_released=False, motor_damping_dt=.2, motor_impulse_limit=limit)
    impulse = -.2*initial/1.2
    if limit is not None:
        impulse = np.clip(impulse, -limit, limit)
    solutions = enumerate_contact_modes(data)
    assert solutions
    for result in solutions:
        assert result['velocity'][3] == pytest.approx(initial+impulse, abs=1e-12)


def test_mode_enumeration_solves_redundant_contacts_without_claiming_unique_loads():
    data = system(velocity=(.2, -1., 0., 0.))
    data['normal_jacobians'] *= 2
    data['tangent_jacobians'] *= 2
    data['penetrations'] *= 2
    solutions = enumerate_contact_modes(data)
    assert solutions
    for result in solutions:
        np.testing.assert_allclose(result['velocity'], 0., atol=1e-12)
    assert any(result['rank'] < 5 for result in solutions)
