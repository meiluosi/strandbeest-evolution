"""Tests for multi-entity herd simulation (ADR-0005, E4-04)."""

import copy
import mujoco
import numpy as np
import pytest

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design
from strandbeest_sim.builder import build_herd

DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")


def test_build_herd_namespaces_bodies_joints_and_equalities():
    sc_solo = scenario_from_design(DESIGN)
    ent_template = sc_solo.entities[0].model_dump(mode="json")

    entA = copy.deepcopy(ent_template)
    entA["name"] = "walkerA"
    entA["placement"] = {"x": 0.0, "y": -1.5, "phase_offset": 0.0}

    entB = copy.deepcopy(ent_template)
    entB["name"] = "walkerB"
    entB["placement"] = {"x": 0.0, "y": 1.5, "phase_offset": 0.5}

    scenario_doc = {
        "schema_version": 2,
        "name": "two-walker-herd",
        "world": sc_solo.world.model_dump(mode="json"),
        "entities": [entA, entB],
        "solver": sc_solo.solver.model_dump(mode="json"),
    }

    herd = build_herd(scenario_doc)
    assert "walkerA" in herd.entities
    assert "walkerB" in herd.entities

    # Verify namespacing
    assert herd.entities["walkerA"].torso_body == "walkerA_torso"
    assert herd.entities["walkerB"].torso_body == "walkerB_torso"
    assert herd.entities["walkerA"].crank_joint == "walkerA_crank0"
    assert herd.entities["walkerB"].crank_joint == "walkerB_crank0"

    # MuJoCo compiles the herd model without error
    model = mujoco.MjModel.from_xml_string(herd.xml)
    data = mujoco.MjData(model)
    assert model.nbody > 30
    assert model.nu == 2  # 2 independent motor actuators

    # Step in physics without instability
    mujoco.mj_step(model, data)
    assert np.isfinite(data.qpos).all()


def test_herd_walkers_match_solo_run_within_tolerance():
    """E4-04 acceptance: Two identical walkers side by side run without collision,

    and each walker's trajectory agrees with a solo walker run within numerical tolerance.
    """
    sc_solo = scenario_from_design(DESIGN)
    ent_template = sc_solo.entities[0].model_dump(mode="json")

    ent_solo = copy.deepcopy(ent_template)
    ent_solo["name"] = "walker"
    ent_solo["placement"] = {"x": 0.0, "y": 0.0, "phase_offset": 0.0}

    scenario_solo = {
        "schema_version": 2,
        "name": "solo-world",
        "world": sc_solo.world.model_dump(mode="json"),
        "entities": [ent_solo],
        "solver": sc_solo.solver.model_dump(mode="json"),
    }

    entA = copy.deepcopy(ent_template)
    entA["name"] = "walkerA"
    entA["placement"] = {"x": 0.0, "y": -2.0, "phase_offset": 0.0}

    entB = copy.deepcopy(ent_template)
    entB["name"] = "walkerB"
    entB["placement"] = {"x": 0.0, "y": 2.0, "phase_offset": 0.0}

    scenario_pair = {
        "schema_version": 2,
        "name": "pair-world",
        "world": sc_solo.world.model_dump(mode="json"),
        "entities": [entA, entB],
        "solver": sc_solo.solver.model_dump(mode="json"),
    }

    # Simulate solo for 400 steps
    solo_built = build_herd(scenario_solo)
    m_solo = mujoco.MjModel.from_xml_string(solo_built.xml)
    d_solo = mujoco.MjData(m_solo)

    pair_built = build_herd(scenario_pair)
    m_pair = mujoco.MjModel.from_xml_string(pair_built.xml)
    d_pair = mujoco.MjData(m_pair)

    # Set motor control targets
    target_angle = 1.0
    d_solo.ctrl[0] = target_angle
    d_pair.ctrl[0] = target_angle
    d_pair.ctrl[1] = target_angle

    for _ in range(400):
        mujoco.mj_step(m_solo, d_solo)
        mujoco.mj_step(m_pair, d_pair)

    solo_torso_id = mujoco.mj_name2id(m_solo, mujoco.mjtObj.mjOBJ_BODY, "walker_torso")
    pair_torsoA_id = mujoco.mj_name2id(m_pair, mujoco.mjtObj.mjOBJ_BODY, "walkerA_torso")
    pair_torsoB_id = mujoco.mj_name2id(m_pair, mujoco.mjtObj.mjOBJ_BODY, "walkerB_torso")

    pos_solo = d_solo.xpos[solo_torso_id]
    pos_pairA = d_pair.xpos[pair_torsoA_id]
    pos_pairB = d_pair.xpos[pair_torsoB_id]

    # X forward travel should match within 1e-4 m
    assert abs(pos_pairA[0] - pos_solo[0]) < 1e-4
    assert abs(pos_pairB[0] - pos_solo[0]) < 1e-4
    # Lateral Y positions remain isolated
    assert pos_pairA[1] == pytest.approx(-2.0, abs=0.01)
    assert pos_pairB[1] == pytest.approx(2.0, abs=0.01)


def test_herd_walkers_torso_collision():
    """Verify that two walkers in a herd physically collide when placed close together."""
    sc_solo = scenario_from_design(DESIGN)
    ent_template = sc_solo.entities[0].model_dump(mode="json")

    # Place two walkers on the same track (y = 0) close together so torso boxes bump
    entA = copy.deepcopy(ent_template)
    entA["name"] = "walkerA"
    entA["placement"] = {"x": 0.0, "y": 0.0, "phase_offset": 0.0}

    entB = copy.deepcopy(ent_template)
    entB["name"] = "walkerB"
    entB["placement"] = {"x": 0.2, "y": 0.0, "phase_offset": 0.0}

    scenario_collision = {
        "schema_version": 2,
        "name": "collision-world",
        "world": sc_solo.world.model_dump(mode="json"),
        "entities": [entA, entB],
        "solver": sc_solo.solver.model_dump(mode="json"),
    }

    built = build_herd(scenario_collision)
    model = mujoco.MjModel.from_xml_string(built.xml)
    data = mujoco.MjData(model)

    torsoA_geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "walkerA_torso_geom")
    torsoB_geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "walkerB_torso_geom")
    assert torsoA_geom >= 0
    assert torsoB_geom >= 0

    # Step physics to detect and resolve collisions
    collided = False
    for _ in range(50):
        mujoco.mj_step(model, data)
        for i in range(data.ncon):
            c = data.contact[i]
            if {c.geom1, c.geom2} == {torsoA_geom, torsoB_geom}:
                collided = True
                break
        if collided:
            break

    assert collided, "Expected torso contact points between walkerA and walkerB"

