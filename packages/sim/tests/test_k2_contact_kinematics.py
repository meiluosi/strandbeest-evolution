"""K2 must execute its declared timestep and use sphere material-point velocity."""
import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from strandbeest_sim.backend import TerrainPlan
from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.builder import build, resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.contract import _example_design, _scenario
from strandbeest_sim.linkage import solve_pose


def config(**overrides):
    return sim_config(_scenario(_example_design(), overrides))


@pytest.mark.parametrize('dt', [.0001, .0005, .001])
def test_walker_executes_scenario_timestep_and_preserves_input(dt):
    sc = config(solver={'timestep': dt})
    before = sc.model_dump()
    backend = K2Backend()
    backend.build(sc, TerrainPlan())
    backend.step(3)
    assert backend.timestep == dt
    assert backend.time == pytest.approx(3*dt, rel=1e-14)
    assert sc.model_dump() == before


def test_hidden_constructor_timestep_cannot_contradict_recorded_scenario():
    sc = config(solver={'timestep': .0001})
    with pytest.raises(ValueError, match='solver.timestep'):
        K2Backend(timestep=.001).build(sc, TerrainPlan())
    # Reference systems remain explicitly configurable without a Scenario.
    backend = K2Backend(timestep=.001)
    backend.build_reference('pendulum')
    backend.step()
    assert backend.time == .001


@pytest.mark.parametrize('legs', [4, 6, 8])
def test_sphere_owner_and_initial_height_match_the_actual_model(legs):
    sc = config(walker={'legs': legs})
    backend = K2Backend()
    backend.build(sc, TerrainPlan())
    native = build(sc, resolve_spec(sc))
    assert backend._q[1] == native.hip_height
    bodies = ET.fromstring(native.xml).iter('body')
    foot_body = next(b for b in bodies if any(g.get('name', '').startswith('foot_bar0_') for g in b.findall('geom')))
    index = int(foot_body.attrib['name'][-1])
    joint = next(j for j in backend._spec.joints if j.id == backend._spec.foot)
    assert backend._foot_owner_start == joint.centers[index]
    assert backend._info.foot_names[0] == foot_body.find("geom[@type='sphere']").attrib['name']


@pytest.mark.parametrize('theta', [-1e-8, 0., 1e-8, .23, math.pi, math.tau-1e-8, math.tau])
def test_periodic_interpolated_position_derivative_matches_position(theta):
    backend = K2Backend()
    backend.build(config(), TerrainPlan())
    h = 1e-6
    at = backend._interp_foot(theta)
    left, right = backend._interp_foot(theta-h), backend._interp_foot(theta+h)
    np.testing.assert_allclose(at[2:4], (np.array(right[:2])-left[:2])/(2*h), rtol=1e-7, atol=1e-8)
    np.testing.assert_allclose(at, backend._interp_foot(theta+math.tau), rtol=1e-10, atol=1e-12)


def test_interpolation_matches_analytic_ellipse_and_sphere_with_two_windings(monkeypatch):
    import strandbeest_sim.backends.k2_backend as module

    def analytic_pose(spec, theta):
        foot = np.array([.3*math.sin(theta), -.8+.2*math.cos(theta)])
        bar = .1*np.array([math.cos(2*theta), math.sin(2*theta)])
        return {**{j.id: foot-bar for j in spec.joints}, 'G': foot-bar, 'C': foot-bar, spec.foot: foot}

    monkeypatch.setattr(module, 'solve_pose', analytic_pose)
    sc = config()
    backend = K2Backend()
    backend.build(sc, TerrainPlan())
    for theta in np.linspace(-math.tau, math.tau, 67)+.00037:
        expected = np.array([.3*math.sin(theta), -.8+.2*math.cos(theta),
                             .3*math.cos(theta), -.2*math.sin(theta)])*sc.walker.unit
        actual = backend._interp_foot(theta)
        np.testing.assert_allclose(actual[:4], expected, rtol=1e-8, atol=1e-11)
        assert actual[4] == pytest.approx(2., rel=1e-8, abs=1e-10)


def rotate(angle, vec):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([c*vec[0]-s*vec[1], s*vec[0]+c*vec[1]])


@pytest.mark.parametrize('direction', [-1, 1])
@pytest.mark.parametrize('phase', [0., .23, math.pi, math.tau-1e-6])
def test_contact_jacobian_matches_independent_material_point_motion(direction, phase):
    sc = config(walker={'pitch': 'free', 'direction': direction})
    backend = K2Backend()
    backend.build(sc, TerrainPlan())
    q = np.array([.2, .3, .17, phase])
    backend._q = q.copy()
    center, jn, jt = backend._foot_contact_kinematics(0)

    def center_and_angle(state):
        pose = solve_pose(backend._spec, direction*state[3])
        foot = np.array(pose[backend._spec.foot])*sc.walker.unit
        bar = np.array(pose[backend._spec.foot])-pose[backend._foot_owner_start]
        return state[:2]+rotate(state[2], foot), state[2]+math.atan2(bar[1], bar[0])

    pos, beta = center_and_angle(q)
    np.testing.assert_allclose(center, pos, rtol=0, atol=1e-8)

    def material_point(state):
        # Follow the same material point, initially at the sphere's bottom.
        pos, angle = center_and_angle(state)
        return pos+rotate(angle-beta, (0., -sc.walker.foot_radius))

    h = 1e-6
    derivative = np.column_stack([(material_point(q+h*e)-material_point(q-h*e))/(2*h) for e in np.eye(4)])
    np.testing.assert_allclose(jt, derivative[0], rtol=3e-5, atol=2e-7)
    np.testing.assert_allclose(jn, derivative[1], rtol=3e-5, atol=2e-7)


def test_locked_pitch_removes_only_the_pitch_column_not_sphere_rolling():
    sc = config(walker={'pitch': 'locked', 'direction': 1})
    backend = K2Backend()
    backend.build(sc, TerrainPlan())
    # An analytically rotating sphere with its center fixed.
    backend._interp_foot = lambda _: (0., -.2, 0., 0., 3.)
    _, jn, jt = backend._foot_contact_kinematics(0)
    assert jn[2] == jt[2] == 0
    assert jt[3] == pytest.approx(3*sc.walker.foot_radius)


def test_impossible_mass_is_not_silently_replaced_with_an_assumed_torso():
    sc = config(walker={'mass': .00001, 'body_mass': None})
    with pytest.raises(ValueError, match='more than the total mass'):
        K2Backend().build(sc, TerrainPlan())


def test_rebuilding_on_rigid_ground_does_not_retain_previous_softness():
    backend = K2Backend()
    sc = config()
    backend.build(sc, TerrainPlan(softness=(1500., 150.)))
    backend.build(sc, TerrainPlan())
    assert backend._contact_softness is None


@pytest.mark.parametrize('limit', [None, .01])
def test_unlimited_and_limited_servo_follow_the_existing_scenario_contract(limit):
    sc = config(drive={'max_torque': limit})
    backend = K2Backend()
    backend.build(sc, TerrainPlan())
    backend.set_actuator_target('drive', .1)
    backend.step()
    # The physical small crank inertia requires implicit servo damping; test
    # the declared force law at its actual velocity, including saturation.
    expected = sc.drive.kp*.1-sc.drive.kv*backend.joint_velocity('crank0')
    if limit is not None:
        expected = max(-limit, min(limit, expected))
    assert backend.actuator_force('drive') == pytest.approx(expected)


def test_zero_torque_limit_is_rejected_by_the_existing_scenario_schema():
    with pytest.raises(ValueError, match='max_torque'):
        config(drive={'max_torque': 0.})
