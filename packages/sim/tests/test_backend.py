"""E4-02: the simulator runs through the PhysicsBackend protocol; only the adapter touches the engine."""

import re
from pathlib import Path

import numpy as np
import pytest
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.backends import make_backend
from strandbeest_sim.runner import make_sim

SRC = Path(__file__).resolve().parents[1] / "src" / "strandbeest_sim"
DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
FAST = {"run": {"revolutions": 0.5, "settle": 0.3, "frame_rate": 0}}


def test_only_the_adapter_imports_the_physics_engine():
    offenders = []
    for p in sorted(SRC.rglob("*.py")):
        if p.name == "mujoco_backend.py":
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if re.match(r"\s*(import mujoco|from mujoco)\b", line):
                offenders.append(f"{p.relative_to(SRC)}:{n}")
    assert offenders == []


def test_unknown_backend_names_say_what_exists():
    with pytest.raises(KeyError, match="mujoco"):
        make_backend("bullet")


def walker():
    return make_sim(scenario_from_design(DESIGN, FAST))


def test_build_info_names_the_bodies_and_feet_in_replay_order():
    sim = walker()
    info = sim.info
    assert info.body_names[0] == "torso" and info.n_legs == DESIGN.walker["legs"]
    assert len(info.foot_names) == info.n_legs and all(n.startswith("foot_") for n in info.foot_names)
    pos, quat = sim.backend.body_poses()
    assert pos.shape == (len(info.body_names), 3) and quat.shape == (len(info.body_names), 4)


def test_snapshot_restore_continues_exactly_like_an_uninterrupted_run_for_a_walker():
    sim = walker()
    b = sim.backend
    b.step(400)
    snap = b.snapshot()
    b.step(600)
    after = (b.joint_position(sim.info.crank_joint), b.body_position("torso"), b.time)
    b.restore(snap)
    b.step(600)
    assert (b.joint_position(sim.info.crank_joint), b.body_position("torso"), b.time) == after


def test_contacts_forces_and_energies_describe_a_standing_walker():
    sim = walker()
    b = sim.backend
    b.step(int(0.3 / b.timestep))
    cs = b.contacts()
    assert cs and all(c.geom1 == "ground" or c.geom2 == "ground" for c in cs)
    f = b.forces()
    mass = sim.scenario.walker.mass if sim.scenario.walker.body_mass is None else sim.scenario.walker.body_mass + sim.info.bar_mass_total
    # the ground carries the weight: net contact force is vertical and about m*g (a few % from the feet still settling)
    assert f.contact_net[2] == pytest.approx(mass * sim.scenario.environment.gravity, rel=0.05)
    assert abs(f.contact_net[0]) < 0.1 * f.contact_net[2]
    assert f.loop_residual < 1e-3
    assert sum(c.force[2] for c in cs) == pytest.approx(f.contact_net[2])
    assert all(c.depth > -1e-6 for c in cs)
    e = b.energies()
    assert e.kinetic >= 0 and e.total == pytest.approx(e.kinetic + e.potential)


def test_set_param_changes_the_world_and_rejects_unknown_paths():
    sim = walker()
    b = sim.backend
    b.set_param("gravity", (0.0, 0.0, -1.62))
    z0 = b.body_position("torso")[2]
    b.step(int(0.2 / b.timestep))
    assert abs(b.body_position("torso")[2] - z0) < 0.005  # a walker standing on the ground stays put
    with pytest.raises(KeyError, match="gravity"):
        b.set_param("viscosity", 3.0)


def test_runs_are_deterministic_bit_for_bit_on_one_platform():
    a = run(scenario_from_design(DESIGN, FAST))
    b = run(scenario_from_design(DESIGN, FAST))
    assert np.array_equal(a.x, b.x) and np.array_equal(a.torque, b.torque) and a.metrics == b.metrics
