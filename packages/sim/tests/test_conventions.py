"""Conventions (docs/CONVENTIONS.md section 4) on the MuJoCo builder and a short walk."""

import mujoco
import numpy as np
import pytest

from strandbeest_common import Design, solve_pose
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.runner import make_sim

DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
FAST = {"run": {"revolutions": 1.2, "settle": 0.3, "frame_rate": 0}}


def test_initial_crank_tip_in_the_world_matches_the_hip_frame_solution_and_hinge_ref_is_minus_theta():
    sim = make_sim(scenario_from_design(DESIGN, FAST))
    m, d = sim.model, sim.data
    mujoco.mj_forward(m, d)
    u = DESIGN.walker["unit_m"]
    leg0_phase = 0.0
    c = solve_pose(DESIGN.spec, leg0_phase)["C"]
    jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "crank0")
    assert m.qpos0[m.jnt_qposadr[jid]] == pytest.approx(-leg0_phase)  # q = -theta
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "crank0")
    geom = next(g for g in range(m.ngeom) if m.geom_bodyid[g] == bid)
    axis = np.zeros(3)
    mujoco.mju_rotVecQuat(axis, np.array([0, 0, m.geom_size[geom][1]]), m.geom_quat[geom])
    tip_local = m.geom_pos[geom] + axis  # the far end of the crank capsule (the one not at the pivot)
    tip_local = max((m.geom_pos[geom] + axis, m.geom_pos[geom] - axis), key=lambda p: np.linalg.norm(p))
    world = d.xpos[bid] + d.xmat[bid].reshape(3, 3) @ tip_local
    torso = d.xpos[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "torso")]
    assert world[0] - torso[0] == pytest.approx(c[0] * u, abs=1e-6)  # x forward
    assert world[2] - torso[2] == pytest.approx(c[1] * u, abs=1e-6)  # hip-frame y is world z


def test_direction_minus_one_walks_forward_and_plus_one_walks_backward():
    forward = run(scenario_from_design(DESIGN, FAST))
    assert forward.x[-1] - forward.x[0] > 0.1
    backward = run(scenario_from_design(DESIGN, {**FAST, "walker": {"direction": 1}}))
    assert backward.x[-1] - backward.x[0] < -0.05
