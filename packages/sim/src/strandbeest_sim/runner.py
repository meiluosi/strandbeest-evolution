"""Stepping loop, written against the PhysicsBackend protocol. Terrain and drive come from registries; every run returns its
resolved config with the arrays."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .backend import BuildInfo, PhysicsBackend
from .backends import make_backend
from .config import Scenario, SimConfig, sim_config
from .registry import drives, metrics, terrains


@dataclass
class Result:
    scenario: SimConfig  # the flat configuration that was run
    t: np.ndarray
    psi: np.ndarray  # crank rotation in the walking direction, rad, unwrapped, 0 at the start of driving
    x: np.ndarray  # torso forward position, m
    z: np.ndarray  # torso height, m
    torque: np.ndarray  # crank torque supplied by the drive, N·m (positive = driving the walker forward)
    metrics: dict[str, Any] = field(default_factory=dict)
    stalled: bool = False
    scene: dict | None = None  # geometry for replay
    frames: dict | None = None  # recorded body poses: t, pos (F,B,3), quat (F,B,4), contact (F,feet), foot_pos, foot_force, foot_slip, com
    series: dict = field(default_factory=dict)  # per-sample series beyond the basic five: foot loads, energies, loop residual, ...


@dataclass
class Sim:
    """Everything a terrain / drive / metric extension may touch."""

    scenario: SimConfig
    backend: PhysicsBackend
    info: BuildInfo

    @property
    def q0(self) -> float:
        return self.info.crank_q0

    def psi(self) -> float:
        d = self.scenario.walker.direction
        return -d * (self.backend.joint_position(self.info.crank_joint) - self.q0)


def make_sim(sc: Scenario | SimConfig, backend: str | PhysicsBackend = "mujoco") -> Sim:
    cfg = sim_config(sc)
    be = make_backend(backend) if isinstance(backend, str) else backend
    info = be.build(cfg, terrains.get(cfg.terrain.kind)(cfg))
    return Sim(cfg, be, info)


def run(sc: Scenario | SimConfig | dict, backend: str | PhysicsBackend = "mujoco") -> Result:
    sc = sim_config(sc)
    sim = make_sim(sc, backend)
    be = sim.backend
    info = sim.info
    drive = drives.get(sc.drive.kind)(sim)
    dt = be.timestep
    rec = sc.run.record_every

    t_, psi_, x_, z_, tau_ = [], [], [], [], []
    ser: dict[str, list] = {k: [] for k in ("loop_residual", "penetration", "foot_normal", "foot_tangent", "foot_slip", "kinetic", "potential",
                                          "e_in", "e_contact", "e_loops", "e_friction", "crank_reaction")}
    e_in = e_contact = e_loops = e_friction = 0.0  # cumulative energy account since the start of driving, J
    f_foot_pos, f_foot_force, f_foot_slip, f_com = [], [], [], []
    max_viol = 0.0
    max_pen = 0.0
    frame_every = max(1, round(1.0 / (sc.run.frame_rate * dt))) if sc.run.frame_rate > 0 else 0
    f_t, f_pos, f_quat, f_contact = [], [], [], []
    settle_steps = int(round(sc.run.settle / dt))
    for _ in range(settle_steps):
        drive.control(sim, 0.0, driving=False)
        be.step()
    psi_start = sim.psi()
    target = sc.run.revolutions * 2 * math.pi
    k = 0
    stalled = False
    t = 0.0
    while sim.psi() - psi_start < target:
        drive.control(sim, t, driving=True)
        be.step()
        t += dt
        # energy account: what the drive puts in, where it goes (rectangle rule at the step rate)
        omega = -sc.walker.direction * be.joint_velocity(info.crank_joint)
        pb = be.power_balance()
        e_in += drive.torque(sim) * omega * dt
        e_contact += pb.contact * dt
        e_loops += pb.equality * dt
        e_friction += (pb.joint_friction + pb.viscous) * dt
        if k % rec == 0:
            t_.append(t)
            psi_.append(sim.psi() - psi_start)
            torso = be.body_position("torso")
            x_.append(torso[0])
            z_.append(torso[2])
            tau_.append(drive.torque(sim))
            pen = be.max_penetration()
            viol = be.forces().loop_residual
            max_pen = max(max_pen, pen)
            max_viol = max(max_viol, viol)
            loads = be.foot_loads()
            en = be.energies()
            for key, val in (("loop_residual", viol), ("penetration", pen), ("foot_normal", [f.normal for f in loads]),
                             ("foot_tangent", [f.tangent for f in loads]), ("foot_slip", [f.slip for f in loads]),
                             ("kinetic", en.kinetic), ("potential", en.potential), ("e_in", e_in), ("e_contact", e_contact),
                             ("e_loops", e_loops), ("e_friction", e_friction), ("crank_reaction", be.constraint_torque(info.crank_joint))):
                ser[key].append(val)
        if frame_every and k % frame_every == 0:
            f_t.append(t)
            pos, quat = be.body_poses()
            f_pos.append(pos)
            f_quat.append(quat)
            f_contact.append(be.foot_contacts())
            loads = be.foot_loads()
            f_foot_pos.append([f.pos for f in loads])
            f_foot_force.append([f.force for f in loads])
            f_foot_slip.append([f.slip for f in loads])
            f_com.append(be.center_of_mass())
        k += 1
        if t > sc.run.max_time:
            stalled = True
            break
        if sc.run.give_up_after and t > sc.run.give_up_after and sim.psi() - psi_start < 0.1:
            stalled = True  # the crank has not moved: the drive cannot start this walker
            break

    res = Result(sc, np.array(t_), np.array(psi_), np.array(x_), np.array(z_), np.array(tau_), stalled=stalled)
    res.series = {k: np.array(v, dtype=float) for k, v in ser.items() if len(v)}
    if f_t:
        res.scene = be.describe_scene()
        res.frames = {"t": np.array(f_t), "pos": np.array(f_pos, np.float32), "quat": np.array(f_quat, np.float32), "contact": np.array(f_contact, bool),
                      "foot_pos": np.array(f_foot_pos, np.float32), "foot_force": np.array(f_foot_force, np.float32),
                      "foot_slip": np.array(f_foot_slip, np.float32), "com": np.array(f_com, np.float32)}
    res.metrics["max_loop_violation"] = max_viol
    res.metrics["max_penetration"] = max_pen  # deepest foot sinkage into the terrain, m
    for name in metrics.names():
        res.metrics.update(metrics.get(name)(res))
    return res
