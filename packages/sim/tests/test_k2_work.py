"""Analytic impulse/force work checks exercise the actual K2 step and runner."""
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from strandbeest_sim import runner
from strandbeest_sim.backend import TerrainPlan
from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.backends.k2_inertia import MassSample
from strandbeest_sim.config import sim_config
from strandbeest_sim.contract import _example_design, _scenario


class AnalyticBody:
    """Known constant mass for force/impact tests of the actual stepper."""
    def __init__(self, mass, inertia):
        self.mass = mass
        self.matrix = np.diag([mass, mass, .9, inertia])
        self.joint_friction = np.zeros(1)
        self.joint_damping = np.zeros(1)

    def sample(self, q, armature=0.):
        matrix = self.matrix.copy()
        matrix[3, 3] += armature
        return MassSample(matrix, self.mass, np.zeros(2), np.zeros(2), np.zeros(2),
                          0., 0., 0., np.ones(1), np.array([[q[0], 0., q[1]]]), np.array([q[2]]))


def body(*, dt=.01, mass=1.7, inertia=.8, gravity=(0.,0.,0.), pitch='locked', iterations=100):
    sc=sim_config(_scenario(_example_design(), {'solver':{'timestep':dt,'iterations':iterations},'walker':{'pitch':pitch},
                 'run':{'settle':0,'record_every':1,'frame_rate':0,'max_time':.099,'revolutions':100}}))
    be=K2Backend()
    info=be.build(sc,TerrainPlan())
    # Known analytic reduced mass, with the actual K2 force/impulse integrator.
    be._m_total=mass
    be._inertia=AnalyticBody(mass,inertia)
    be._mass_cache=None
    be._q=np.array([0.,10.,0.,0.])
    be._v=np.zeros(4)
    be._gravity=gravity
    be._joint_friction_coeff=0.
    be.release_actuator('drive')
    return sc,be,info


def one_plane_contact(be, penetration):
    # A plane touching one translating sphere; all other feet are clear.
    be._foot_contact_kinematics=lambda leg: (
        np.array([0.,be._foot_radius-penetration if leg==0 else 1.]),
        np.array([0.,1.,0.,0.]),np.array([1.,0.,0.,0.]))


@pytest.mark.parametrize('velocity,force', [(0.,1.),(0.,-1.),(2.,1.),(-2.,-1.),(2.,-1.),(-2.,1.)])
def test_actual_runner_work_matches_constant_torque_solution(monkeypatch,velocity,force):
    sc,be,info=body()
    be._v[3]=velocity
    inertia=be.mass_matrix()[3,3]
    class Drive:
        def control(self,sim,t,driving):sim.backend.apply_joint_torque('crank0',force)
        def torque(self,sim):return force
    monkeypatch.setattr(runner,'make_sim',lambda *args,**kwargs:runner.Sim(sc,be,info))
    monkeypatch.setattr(runner,'drives',SimpleNamespace(get=lambda kind:lambda sim:Drive(),meta=lambda kind:{'energy_source':'test_rig'}))
    result=runner.run(sc)
    expected=.5*inertia*((velocity+force/inertia*result.t)**2-velocity**2)
    np.testing.assert_allclose(result.series['e_in'],expected,rtol=1e-12,atol=1e-14)
    np.testing.assert_array_equal(result.series['e_numerical'],0.)


@pytest.mark.parametrize('force,velocity', [(1.2,0.),(-1.2,2.)])
def test_body_force_and_braking_have_signed_work(force,velocity):
    _,be,_=body()
    be._v[0]=velocity
    be.apply_joint_torque('tx',force)
    be.step()
    expected=force*(velocity+.5*force/be._m_total*be.timestep)*be.timestep
    assert be.step_work().input==pytest.approx(expected,abs=1e-14)
    assert (expected<0)==(force<0)


@pytest.mark.parametrize('velocity', [-2.,2.])
def test_friction_and_damping_work_equal_analytic_loss(velocity):
    _,be,_=body()
    be._inertia.joint_friction[:]=.1
    be._inertia.joint_damping[:]=.3
    be._v[3]=velocity
    inertia=be.mass_matrix()[3,3]
    after=(velocity-np.sign(velocity)*.1/inertia*be.timestep)/(1+.3/inertia*be.timestep)
    be.step()
    expected=.5*inertia*(velocity**2-after**2)
    assert be.step_work().joint_friction+be.step_work().viscous==pytest.approx(expected,abs=1e-14)
    assert be.step_work().input==0.


def test_zero_speed_does_not_charge_friction_that_was_not_applied():
    _,be,_=body()
    be._inertia.joint_friction[:]=.5
    be.apply_joint_torque('crank0',.2)
    be.step()
    assert be._v[3]>0
    assert be.step_work().joint_friction==0


@pytest.mark.parametrize('vx,vz,mu', [(1.,-2.,.5),(3.,-1.,.5),(-3.,-1.,.5),(0.,-2.,0.)])
def test_normal_impact_and_sticking_or_sliding_loss_use_impulse_work(vx,vz,mu):
    _,be,_=body()
    one_plane_contact(be,1e-12)
    be._foot_friction=mu
    be._v[:2]=[vx,vz]
    m=be._m_total
    after_x=np.sign(vx)*max(0.,abs(vx)-mu*abs(vz))
    be.step()
    work=be.step_work()
    assert be._v[0]==pytest.approx(after_x,abs=1e-10)
    assert be._v[1]==pytest.approx(0.,abs=1e-10)
    assert work.contact_normal==pytest.approx(.5*m*vz*vz,abs=1e-10)
    assert work.contact_tangent==pytest.approx(.5*m*(vx*vx-after_x*after_x),abs=1e-10)
    assert work.contact==pytest.approx(work.contact_normal+work.contact_tangent)


def test_penetration_stabilization_energy_injection_is_signed_and_not_clipped():
    _,be,_=body()
    one_plane_contact(be,.001)
    before=be.energies().total
    be.step()
    assert be.step_work().contact_normal<0
    assert be.energies().total-before==pytest.approx(-be.step_work().contact,abs=1e-14)
    assert be.step_work().numerical==0.


def test_symplectic_gravity_defect_is_reported_without_charging_it_as_physical_work():
    dt,m,g=.01,1.7,9.81
    _,be,_=body(dt=dt,mass=m,gravity=(0.,0.,-g))
    before=be.energies().total
    be.step()
    work=be.step_work()
    expected=-.5*m*g*g*dt*dt
    assert be.energies().total-before==pytest.approx(expected,abs=1e-12)
    assert work.numerical==pytest.approx(expected,abs=1e-12)
    assert work.input==work.contact==work.joint_friction==work.viscous==0.


def test_diagonal_analytic_body_has_no_extra_generalized_torso_motor_torque():
    _,be,_=body(pitch='free')
    be._v[2]=.7
    be.apply_joint_torque('crank0',.2)
    before=be.energies().total
    be.step()
    assert be._v[2]==pytest.approx(.7,abs=1e-15)
    assert be.energies().total-before==pytest.approx(be.step_work().input,abs=1e-14)


def test_snapshot_restore_preserves_forces_load_history_and_last_work():
    _,be,_=body()
    one_plane_contact(be,1e-5)
    be._joint_friction_coeff=.2
    be._v[:2]=[.5,-1.]
    be.apply_joint_torque('crank0',.2)
    be.apply_joint_torque('tx',.3)
    be.step(3)
    saved=be.snapshot()
    saved_work=be.step_work()
    expected=copy.deepcopy(be)
    expected.step(20)
    be.apply_joint_torque('tx',-4.)
    be.set_param('gravity',(0.,0.,-1.62))
    be.configure_joint('crank0',armature=.3,damping=.2,frictionloss=.1)
    be.step(4)
    be.restore(saved)
    assert be.step_work()==saved_work
    be.step(20)
    np.testing.assert_array_equal(be._q,expected._q)
    np.testing.assert_array_equal(be._v,expected._v)
    assert be.step_work()==expected.step_work()


def test_reading_work_does_not_change_physics_or_return_mutable_shared_state():
    _,be,_=body()
    be.apply_joint_torque('crank0',.2)
    be.step()
    q,v=be._q.copy(),be._v.copy()
    value=be.step_work()
    assert value==be.step_work()
    np.testing.assert_array_equal(q,be._q)
    np.testing.assert_array_equal(v,be._v)
    with pytest.raises((AttributeError,TypeError)):
        value.input=99


@pytest.mark.parametrize('velocity', [-2., 2.])
@pytest.mark.parametrize('kv', [1., 20.])
@pytest.mark.parametrize('limit', [None, .001])
def test_light_rotor_implicit_servo_is_stable_and_accounts_actual_braking_work(velocity, kv, limit):
    dt, inertia = .01, .0001
    _, be, _ = body(dt=dt, inertia=inertia)
    be._actuator_released = False
    be._v[3] = velocity
    be._kv = kv
    be._max_torque = limit
    expected_impulse = -kv*dt*velocity/(1+kv*dt/inertia)
    if limit is not None:
        expected_impulse = np.clip(expected_impulse, -limit*dt, limit*dt)
    expected_velocity = velocity+expected_impulse/inertia
    be.step()
    assert be._v[3] == pytest.approx(expected_velocity, rel=1e-11, abs=1e-14)
    assert abs(be._v[3]) < abs(velocity)
    assert be.step_work().input == pytest.approx(.5*inertia*(expected_velocity**2-velocity**2), abs=1e-14)
    assert be.step_work().input < 0
    assert be.step_work().numerical == 0
