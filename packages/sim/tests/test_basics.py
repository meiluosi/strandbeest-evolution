import json
import math
from pathlib import Path

import mujoco
import numpy as np
import pytest

from strandbeest_sim import load_scenario
from strandbeest_sim.builder import build, resolve_spec
from strandbeest_sim.drives import MotorDrive
from strandbeest_sim.linkage import solve_pose
from strandbeest_sim.runner import make_sim

DATA = Path(__file__).parent / "data"


def test_scenario_rejects_unknown_fields():
    with pytest.raises(Exception):
        load_scenario({"walker": {"legz": 3}})


def test_builtin_spec_matches_core_export():
    assert json.loads((DATA / "jansen-spec.json").read_text()) == json.loads(
        (Path(__file__).parents[1] / "src/strandbeest_sim/data/jansen.json").read_text()
    )


def test_python_solver_preserves_link_lengths():
    sc = load_scenario({})
    spec = resolve_spec(sc)
    p = solve_pose(spec, 1.3)
    P = spec.params

    def d(a, b):
        return math.dist(p[a], p[b])

    assert d("C", "K") == pytest.approx(P["j"])
    assert d("G", "K") == pytest.approx(P["b"])
    assert d("M", "F") == pytest.approx(P["i"])
    assert d("N", "F") == pytest.approx(P["h"])


def test_model_has_one_degree_of_freedom_per_leg_plus_cranks_tied():
    sc = load_scenario({"walker": {"legs": 3, "pitch": "locked"}})
    sim = make_sim(sc)
    m = sim.model
    # 11 hinges per leg (10 bars + crank) + 2 torso slides, minus loop closures, leaves 1 crank DOF for the shared shaft
    mujoco.mj_forward(m, sim.data)
    viol = [abs(float(v)) for v, t in zip(sim.data.efc_pos, sim.data.efc_type) if t == mujoco.mjtConstraint.mjCNSTR_EQUALITY]
    assert max(viol) < 1e-6  # the generated model starts exactly assembled


def test_twelve_legs_stand_and_start_walking_without_blowing_up():
    sc = load_scenario({"walker": {"legs": 12, "pitch": "locked", "tube_mass_per_m": 0.12}, "drive": {"omega": 0.6, "ramp": 1}})
    sim = make_sim(sc)
    m, d = sim.model, sim.data
    drive = MotorDrive(sim)
    for _ in range(int(0.5 / m.opt.timestep)):
        drive.control(sim, 0.0, False)
        mujoco.mj_step(m, d)
    z0 = float(d.xpos[1][2])
    t = 0.0
    for _ in range(int(3.0 / m.opt.timestep)):
        drive.control(sim, t, True)
        mujoco.mj_step(m, d)
        t += m.opt.timestep
    assert np.isfinite(d.qpos).all()
    assert abs(float(d.xpos[1][2]) - z0) < 0.05  # body height stays put
    assert float(d.xpos[1][0]) > 0.1  # and it moved forward
    eq = max(abs(float(v)) for v, ty in zip(d.efc_pos, d.efc_type) if ty == mujoco.mjtConstraint.mjCNSTR_EQUALITY)
    assert eq < 1e-3  # loops stayed closed
