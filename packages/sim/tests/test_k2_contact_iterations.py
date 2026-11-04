"""The configured contact budget must solve the coupled physical equations."""
import numpy as np
import pytest

from test_k2_work import body, one_plane_contact


def coupled_body(iterations, *, kv=10., crank_velocity=1.):
    _, be, _ = body(iterations=iterations)
    a, b, penetration = .8, .5, 1e-6
    be._foot_contact_kinematics = lambda leg: (
        np.array([0., be._foot_radius-penetration if leg == 0 else 1.]),
        np.array([0., 1., 0., a]), np.array([1., 0., 0., b]))
    be._v[:] = [.2, -2., 0., crank_velocity]
    be._foot_friction = 2.
    be._actuator_released = False
    be._kp, be._kv = 0., kv
    be._max_torque = None
    # Solve momentum + sticking + unsaturated motor law simultaneously,
    # without reproducing the sequential impulse iteration.
    mass, inertia, dt = be._m_total, be.mass_matrix()[3, 3], be.timestep
    normal_target = .15*penetration/dt
    speed = (inertia*crank_velocity-mass*b*.2+mass*a*(normal_target+2.)) / (
        inertia+mass*(a*a+b*b)+kv*dt)
    expected = np.array([-b*speed, normal_target-a*speed, 0., speed])
    pn = mass*(expected[1]+2.)
    pt = mass*(expected[0]-.2)
    assert pn > 0 and abs(pt) < be._foot_friction*pn
    return be, expected


@pytest.mark.parametrize('kv', [1., 10., 30.])
@pytest.mark.parametrize('crank_velocity', [-1., 1.])
def test_configured_iterations_reach_coupled_sticking_motor_solution(kv, crank_velocity):
    be, expected = coupled_body(100, kv=kv, crank_velocity=crank_velocity)
    be.step()
    np.testing.assert_allclose(be._v, expected, rtol=1e-12, atol=1e-12)
    assert 1 <= be._last_contact_iterations <= 100


def test_iteration_budget_reaches_the_actual_coupled_solve(monkeypatch):
    import strandbeest_sim.backends.k2_backend as module
    actual = module.solve_contacts
    budgets = []

    def observed(**kwargs):
        budgets.append(kwargs['iterations'])
        return actual(**kwargs)

    monkeypatch.setattr(module, 'solve_contacts', observed)
    for iterations in (1, 2, 12, 100):
        be, expected = coupled_body(iterations)
        be.step()
        assert 1 <= be._last_contact_iterations <= iterations
        np.testing.assert_allclose(be._v, expected, rtol=1e-12, atol=1e-12)
    assert budgets == [1, 2, 12, 100]


def test_converged_contact_can_finish_before_the_budget():
    _, be, _ = body(iterations=100)
    one_plane_contact(be, 0.001)
    be.step()
    assert be._v[1] == pytest.approx(.15*.001/be.timestep, abs=1e-15)
    assert 1 <= be._last_contact_iterations < 100
