"""Inertia, gravity and velocity coupling need independent evidence, not a green energy ledger."""
import math

import numpy as np
import pytest

from strandbeest_sim.backend import TerrainPlan
from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.backends.k2_inertia import WalkerInertia, capsule_inertia
from strandbeest_sim.builder import build, resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.contract import _example_design, _scenario
from k2_inertia_reference import NativeReducedOracle


def config(**kwargs):
    return sim_config(_scenario(_example_design(), {'walker': {'pitch': 'free', **kwargs}}))


@pytest.mark.parametrize('length,radius', [(0., .2), (.7, .2), (2., .01)])
def test_capsule_inertia_matches_independent_volume_quadrature(length, radius):
    # Integrate cross-sectional disks about the transverse axis; no use of the
    # cylinder/cap analytic expression from the implementation.
    def disk_radius_squared(z):
        return radius**2-np.maximum(np.abs(z)-length/2, 0.)**2
    limit = length/2+radius
    nodes, weights = np.polynomial.legendre.leggauss(16)
    volume = moment = 0.
    for left, right in [(-limit, -length/2), (-length/2, length/2), (length/2, limit)]:
        z = (right+left)/2+(right-left)/2*nodes
        area = math.pi*disk_radius_squared(z)
        volume += float((weights @ area)*(right-left)/2)
        moment += float((weights @ (area*(z*z+disk_radius_squared(z)/4)))*(right-left)/2)
    assert capsule_inertia(1.3, length, radius) == pytest.approx(1.3*moment/volume, rel=1e-11)


@pytest.mark.parametrize('direction', [-1, 1])
@pytest.mark.parametrize('phase', [0., .271, 2.91, math.tau-1e-4])
def test_full_mass_gravity_and_velocity_bias_match_native_projection(direction, phase):
    sc = config(direction=direction)
    spec = resolve_spec(sc)
    geometry = WalkerInertia(spec, sc, build(sc, spec).xml)
    q = np.array([.12, .8, .23, phase])
    velocity = np.array([.2, -.13, .3, 1.7])
    gravity = (-2., 0., -9.)
    sample = geometry.sample(q, armature=.00013)
    expected = NativeReducedOracle(sc).evaluate(q, velocity, gravity, armature=.00013)
    np.testing.assert_allclose(sample.matrix, expected['mass'], rtol=3e-6, atol=3e-10)
    np.testing.assert_allclose(sample.bias(velocity)-sample.gravity(gravity), expected['bias_minus_gravity'], rtol=3e-5, atol=3e-7)
    assert sample.potential(q, gravity) == pytest.approx(expected['potential'], rel=1e-8, abs=1e-9)
    np.testing.assert_allclose(q[:2]+sample.moment/sample.mass, expected['com'][[0, 2]], rtol=1e-8, atol=1e-9)
    np.testing.assert_allclose(sample.body_positions, expected['body_positions'], rtol=1e-8, atol=1e-9)
    for angle, rotation in zip(sample.body_angles, expected['body_rotations']):
        c, s = math.cos(angle), math.sin(angle)
        np.testing.assert_allclose(rotation, [[c, 0, -s], [0, 1, 0], [s, 0, c]], rtol=1e-7, atol=1e-9)
    assert np.linalg.eigvalsh(sample.matrix).min() > 0


def test_configuration_dependent_energy_derivative_equals_velocity_bias_power():
    sc = config()
    spec = resolve_spec(sc)
    geometry = WalkerInertia(spec, sc, build(sc, spec).xml)
    q, v = np.array([.1, .5, -.2, .72]), np.array([.13, -.2, .3, 2.])
    sample = geometry.sample(q)
    h = 1e-5
    derivative = (geometry.sample(q+h*v).matrix-geometry.sample(q-h*v).matrix)/(2*h)
    assert v@sample.bias(v) == pytest.approx(.5*v@derivative@v, rel=2e-6, abs=2e-10)
    g = (-1., 0., -9.81)
    grad = np.array([(geometry.sample(q+h*e).potential(q+h*e, g)-geometry.sample(q-h*e).potential(q-h*e, g))/(2*h) for e in np.eye(4)])
    np.testing.assert_allclose(grad, -sample.gravity(g), rtol=2e-7, atol=2e-9)


def test_backend_uses_the_complete_mass_and_center_of_mass_in_actual_energy():
    sc = config()
    backend = K2Backend()
    backend.build(sc, TerrainPlan())
    backend._q = q = np.array([.2, .6, -.21, .43])
    backend._v = v = np.array([.15, -.1, .4, 1.9])
    expected = NativeReducedOracle(sc).evaluate(q, v)
    np.testing.assert_allclose(backend.mass_matrix(), expected['mass'], rtol=3e-6, atol=3e-10)
    assert backend.energies().kinetic == pytest.approx(.5*v@expected['mass']@v, rel=3e-6)
    assert backend.energies().potential == pytest.approx(expected['potential'], rel=1e-8)
    np.testing.assert_allclose(backend.center_of_mass(), expected['com'], rtol=1e-8, atol=1e-9)
    # The old fixed .001 kg m^2 crank inertia and torso-only gravity cannot pass.
    assert abs(expected['mass'][2, 3]) > 1e-6
    returned = backend.mass_matrix()
    returned[:] = 0
    np.testing.assert_allclose(backend.mass_matrix(), expected['mass'], rtol=3e-6, atol=3e-10)
    positions, quaternions = backend.body_poses()
    np.testing.assert_allclose(positions, expected['body_positions'], atol=5e-8)
    for quat, rotation in zip(quaternions, expected['body_rotations']):
        # Rotation about world y; the sign must match positive CCW in x/z.
        c, s = 1-2*quat[2]**2, 2*quat[0]*quat[2]
        np.testing.assert_allclose(rotation, [[c, 0, s], [0, 1, 0], [-s, 0, c]], atol=2e-7)


def test_internal_motor_conserves_free_body_linear_and_angular_momentum_to_step_accuracy():
    sc = config()
    sc.solver.timestep = 1e-5
    be = K2Backend()
    be.build(sc, TerrainPlan())
    be._q = np.array([0., 10., 0., .7])
    be.set_param('gravity', (0., 0., 0.))
    be.release_actuator('drive')
    be.apply_joint_torque('crank0', .001)
    before = be.center_of_mass()
    be.step(100)
    momentum = be.mass_matrix() @ be._v
    np.testing.assert_allclose(momentum[:3], 0., atol=2e-9)
    np.testing.assert_allclose(be.center_of_mass(), before, atol=2e-9)
    assert be._v[2]*be._v[3] < 0  # counterrotation follows from inertia coupling


def test_locked_pitch_uses_the_restricted_mass_not_full_inverse_then_zeroing():
    sc = config(pitch='locked')
    be = K2Backend()
    be.build(sc, TerrainPlan())
    be._q[1] = 10.
    be.set_param('gravity', (0., 0., 0.))
    be.release_actuator('drive')
    be.apply_joint_torque('crank0', .001)
    active = np.array([0, 1, 3])
    expected = np.linalg.solve(be.mass_matrix()[np.ix_(active, active)], [0., 0., .001])*be.timestep
    be.step()
    np.testing.assert_allclose(be._v[active], expected, rtol=1e-12, atol=1e-14)
    assert be._v[2] == be._q[2] == 0.
