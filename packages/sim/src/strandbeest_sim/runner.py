"""Stepping loop. Terrain and drive come from registries; every run returns its resolved config with the arrays."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import mujoco
import numpy as np

from .builder import Built, build, resolve_spec
from .config import Scenario
from .registry import drives, metrics, terrains


@dataclass
class Result:
    scenario: Scenario
    t: np.ndarray
    psi: np.ndarray  # crank rotation in the walking direction, rad, unwrapped, 0 at the start of driving
    x: np.ndarray  # torso forward position, m
    z: np.ndarray  # torso height, m
    torque: np.ndarray  # crank torque supplied by the drive, N·m (positive = driving the walker forward)
    metrics: dict[str, Any] = field(default_factory=dict)
    stalled: bool = False


@dataclass
class Sim:
    """Everything a terrain / drive / metric extension may touch."""

    scenario: Scenario
    built: Built
    model: mujoco.MjModel
    data: mujoco.MjData
    crank_qadr: int
    crank_dofadr: int
    q0: float

    def psi(self) -> float:
        d = self.scenario.walker.direction
        return -d * (float(self.data.qpos[self.crank_qadr]) - self.q0)


def make_sim(sc: Scenario) -> Sim:
    spec = resolve_spec(sc)
    built = build(sc, spec)
    model = mujoco.MjModel.from_xml_string(built.xml)
    data = mujoco.MjData(model)
    terrains.get(sc.terrain.kind)(sc, model)
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, built.crank_joint)
    sim = Sim(sc, built, model, data, int(model.jnt_qposadr[jid]), int(model.jnt_dofadr[jid]), built.crank_q0)
    mujoco.mj_forward(model, data)
    return sim


def run(sc: Scenario) -> Result:
    sim = make_sim(sc)
    m, d = sim.model, sim.data
    drive = drives.get(sc.drive.kind)(sim)
    dt = m.opt.timestep
    rec = sc.run.record_every
    torso = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "torso")

    t_, psi_, x_, z_, tau_ = [], [], [], [], []
    max_viol = 0.0
    settle_steps = int(round(sc.run.settle / dt))
    for _ in range(settle_steps):
        drive.control(sim, 0.0, driving=False)
        mujoco.mj_step(m, d)
    psi_start = sim.psi()
    target = sc.run.revolutions * 2 * math.pi
    k = 0
    stalled = False
    t = 0.0
    while sim.psi() - psi_start < target:
        drive.control(sim, t, driving=True)
        mujoco.mj_step(m, d)
        t += dt
        if k % rec == 0:
            t_.append(t)
            psi_.append(sim.psi() - psi_start)
            x_.append(float(d.xpos[torso][0]))
            z_.append(float(d.xpos[torso][2]))
            tau_.append(drive.torque(sim))
            if d.nefc:
                eqm = d.efc_type == mujoco.mjtConstraint.mjCNSTR_EQUALITY
                if eqm.any():
                    max_viol = max(max_viol, float(np.abs(d.efc_pos[eqm]).max()))
        k += 1
        if t > sc.run.max_time:
            stalled = True
            break

    res = Result(sc, np.array(t_), np.array(psi_), np.array(x_), np.array(z_), np.array(tau_), stalled=stalled)
    res.metrics["max_loop_violation"] = max_viol
    for name in metrics.names():
        res.metrics.update(metrics.get(name)(res))
    return res
