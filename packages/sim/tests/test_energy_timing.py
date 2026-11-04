"""H2-01: synchronized energy and work, checked against analytic systems.

These exercise runner.run against actual MuJoCo systems. No alternative
integration implementation is substituted for the production energy account.
"""

from __future__ import annotations

from types import SimpleNamespace

import mujoco
import numpy as np
import pytest

from strandbeest_sim import runner
from strandbeest_sim.backend import BuildInfo, TerrainPlan
from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.backends.mujoco_backend import MujocoBackend
from strandbeest_sim.config import SimConfig


class AnalyticBackend(MujocoBackend):
    """One translational DOF using the runner's crank channel to measure work."""

    def __init__(self, *, dt: float, velocity: float, position: float, damping: float, stiffness: float):
        super().__init__()
        self._load_reference(
            f'<mujoco><option timestep="{dt}" gravity="0 0 0" integrator="implicitfast"/>'
            '<worldbody><body name="torso">'
            f'<joint name="crank0" type="slide" axis="1 0 0" damping="{damping}" stiffness="{stiffness}"/>'
            '<geom type="sphere" size="0.1" mass="1"/></body></worldbody></mujoco>'
        )
        self.data.qpos[0] = position
        self.data.qvel[0] = velocity
        mujoco.mj_forward(self.model, self.data)
        self.trace = []

    def joint_velocity(self, name: str) -> float:
        # The runner also asks for body x velocity, which is this same DOF.
        return super().joint_velocity("crank0" if name == "tx" else name)

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            super().step()
            self.trace.append((self.data.qpos.copy(), self.data.qvel.copy()))


class ConstantDrive:
    def __init__(self, force: float, drag: float = 0.0):
        self.force = force
        self.drag = drag

    def control(self, sim, t, driving):
        sim.backend.apply_joint_torque("crank0", self.force + self.drag)

    def torque(self, sim):
        return self.force

    def body_drag_force(self, sim):
        return self.drag


def run_analytic(monkeypatch, *, velocity=0.0, force=0.0, dt=0.01, position=0.0, damping=0.0, stiffness=0.0, drag=0.0):
    backend = AnalyticBackend(dt=dt, velocity=velocity, position=position, damping=damping, stiffness=stiffness)
    cfg = SimConfig.model_validate({
        "walker": {"direction": -1},
        "run": {"revolutions": 100, "max_time": 0.99, "settle": 0, "record_every": 1, "frame_rate": 0},
    })
    info = BuildInfo(0, "crank0", 0.0, "unused", 0.0, 0.0, ("torso",), ())
    sim = runner.Sim(cfg, backend, info)
    monkeypatch.setattr(runner, "make_sim", lambda *args, **kwargs: sim)
    monkeypatch.setattr(runner, "drives", SimpleNamespace(
        get=lambda kind: lambda sim: ConstantDrive(force, drag),
        meta=lambda kind: {"energy_source": "test_rig"},
    ))
    result = runner.run(cfg)
    return result, backend


@pytest.mark.parametrize("velocity,force", [(0.0, 1.0), (0.0, -1.0), (2.0, 1.0), (-2.0, -1.0), (2.0, -1.0), (-2.0, 1.0)])
def test_constant_force_work_matches_analytic_energy_at_reported_time(monkeypatch, velocity, force):
    result, _ = run_analytic(monkeypatch, velocity=velocity, force=force)
    expected_kinetic = 0.5 * (velocity + force * result.t) ** 2
    expected_work = expected_kinetic - 0.5 * velocity**2
    np.testing.assert_allclose(result.series["kinetic"], expected_kinetic, rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(result.series["e_in"], expected_work, rtol=1e-12, atol=1e-14)


def test_braking_mass_reports_negative_work_without_omitting_its_energy_balance(monkeypatch):
    result, _ = run_analytic(monkeypatch, velocity=2.0, force=-1.0)
    assert result.metrics["energy_in_per_rev"] < 0.0
    assert abs(result.metrics["energy_residual_share"]) < 1e-12


@pytest.mark.parametrize("velocity", [-2.0, 2.0])
def test_damped_mass_energy_is_synchronized_and_closes_with_derived_integration_bound(monkeypatch, velocity):
    damping, dt = 0.5, 0.001
    result, _ = run_analytic(monkeypatch, velocity=velocity, damping=damping, dt=dt)
    # MuJoCo implicitfast exactly follows v[n+1] = v[n] / (1 + c*dt/m)
    # for this linear 1 kg system; this separates recording error from the
    # known first-order discretization of the physical solution exp(-c*t/m).
    a = damping * dt
    step_index = np.rint(result.t / dt)
    expected_kinetic = 0.5 * (velocity / (1 + a) ** step_index) ** 2
    np.testing.assert_allclose(result.series["kinetic"], expected_kinetic, rtol=1e-12, atol=1e-14)
    np.testing.assert_array_equal(result.series["e_in"], 0)
    loss = 0.5 * velocity**2 - expected_kinetic
    # Implicit damping force -c*v_next times average velocity exactly
    # matches the finite change in kinetic energy for this linear mass.
    np.testing.assert_allclose(result.series["e_friction"], loss, rtol=1e-11, atol=1e-12)


def test_conservative_oscillator_reports_potential_at_the_same_position(monkeypatch):
    position, stiffness, dt = 0.25, 4.0, 0.001
    result, _ = run_analytic(monkeypatch, position=position, stiffness=stiffness, dt=dt)
    recorded_position = result.psi + position
    np.testing.assert_allclose(result.series["potential"], 0.5 * stiffness * recorded_position**2, rtol=1e-12, atol=1e-14)
    total = result.series["potential"] + result.series["kinetic"]
    initial = 0.5 * stiffness * position**2
    # First-order symplectic integration has bounded O(dt*sqrt(k/m)) energy
    # oscillation; no drive or friction work should appear in this system.
    assert np.max(np.abs(total - initial)) < initial * dt * np.sqrt(stiffness)
    np.testing.assert_array_equal(result.series["e_in"], 0)
    np.testing.assert_array_equal(result.series["e_friction"], 0)


def test_recording_does_not_change_the_underlying_physics_trajectory(monkeypatch):
    velocity, force, dt, damping = -0.4, 0.7, 0.01, 0.3
    _, observed = run_analytic(monkeypatch, velocity=velocity, force=force, dt=dt, damping=damping)
    plain = AnalyticBackend(dt=dt, velocity=velocity, position=0.0, damping=damping, stiffness=0.0)
    for expected_pos, expected_vel in observed.trace:
        plain.apply_joint_torque("crank0", force)
        plain.step()
        np.testing.assert_array_equal(plain.data.qpos, expected_pos)
        np.testing.assert_array_equal(plain.data.qvel, expected_vel)


@pytest.mark.parametrize("slope,displacement", [(15.0, 2.0), (-15.0, 2.0), (15.0, -2.0)])
def test_k2_slope_potential_includes_work_against_horizontal_gravity(slope, displacement):
    backend = K2Backend()
    backend.build(SimConfig(), TerrainPlan(slope_deg=slope))
    before = backend.energies().potential
    backend._q[0] += displacement
    after = backend.energies().potential
    expected_change = -backend._m_total * backend._gravity[0] * displacement
    assert after - before == pytest.approx(expected_change, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("velocity,drag", [(0.0, 1.0), (0.0, -1.0), (2.0, -0.5), (-2.0, 0.5)])
def test_external_body_force_contributes_to_input_work(monkeypatch, velocity, drag):
    result, _ = run_analytic(monkeypatch, velocity=velocity, force=0.25, drag=drag)
    expected = 0.5 * (velocity + (0.25 + drag) * result.t)**2 - 0.5 * velocity**2
    np.testing.assert_allclose(result.series["e_in"], expected, rtol=1e-12, atol=1e-14)
    assert result.t[0] == 0.0 and result.series["e_in"][0] == 0.0


@pytest.mark.parametrize("velocity,target,limit", [(0., 1., None), (0., -1., None), (2., -1., None), (-2., 1., None), (0., 1., .5), (0., -1., .5)])
def test_implicit_servo_work_uses_velocity_bias_but_not_future_position_feedback(velocity, target, limit):
    dt, kp, kv = .05, 10., 3.
    backend = MujocoBackend()
    limited = f'forcerange="{-limit} {limit}"' if limit else ""
    backend._load_reference(
        f'<mujoco><option timestep="{dt}" gravity="0 0 0" integrator="implicitfast"/>'
        '<worldbody><body><joint name="j" type="slide" axis="1 0 0"/>'
        '<geom type="sphere" size=".1" mass="1"/></body></worldbody>'
        f'<actuator><position name="servo" joint="j" kp="{kp}" kv="{kv}" {limited}/></actuator></mujoco>'
    )
    backend.data.qvel[0] = velocity
    backend.data.ctrl[0] = target
    cumulative = 0.
    initial = .5 * velocity**2
    for _ in range(30):
        before_pos, before_vel = float(backend.data.qpos[0]), float(backend.data.qvel[0])
        raw_force = kp * (target - before_pos) - kv * before_vel
        clamped = limit is not None and abs(raw_force) >= limit
        force = float(np.clip(raw_force, -limit, limit)) if limit else raw_force
        expected_vel = before_vel + dt * force / (1 + (0 if clamped else dt * kv))
        backend.step()
        assert backend.data.qvel[0] == pytest.approx(expected_vel, abs=1e-13)
        observed = backend.step_observation()
        assert observed.joint_position("j") == before_pos
        assert observed.joint_velocity("j") == before_vel
        assert observed.energies().kinetic == pytest.approx(.5 * before_vel**2, abs=1e-13)
        effective = backend.step_actuator_force("servo")
        cumulative += effective * .5 * (before_vel + expected_vel) * dt
        assert cumulative == pytest.approx(.5 * expected_vel**2 - initial, abs=1e-12)


def test_real_walker_observation_and_work_do_not_change_integration():
    cfg = SimConfig.model_validate({"run": {"settle": 0, "revolutions": .1}})
    observed, plain = runner.make_sim(cfg), runner.make_sim(cfg)
    from strandbeest_sim.drives import MotorDrive
    first, second = MotorDrive(observed), MotorDrive(plain)
    for k in range(1000):
        t = k * observed.backend.timestep
        first.control(observed, t, driving=True)
        second.control(plain, t, driving=True)
        observed.backend.step()
        observed.backend.step_observation()
        observed.backend.step_power_balance()
        first.step_torque(observed)
        plain.backend.step()
        np.testing.assert_array_equal(observed.backend.data.qpos, plain.backend.data.qpos)
        np.testing.assert_array_equal(observed.backend.data.qvel, plain.backend.data.qvel)
        np.testing.assert_array_equal(observed.backend.data.qacc_warmstart, plain.backend.data.qacc_warmstart)
