"""Mass-normalised contact parameters, checked against native constraint dynamics.

These tests do not use a newly generated walker trajectory as their oracle.
MuJoCo's documented positive/direct solref equivalence and a one-dimensional
contact with constant impedance independently fix the requested damping ratio.
"""

import copy
import json
import math
from xml.etree import ElementTree

import mujoco
import numpy as np
import pytest
from jsonschema import Draft202012Validator

from strandbeest_common import Design
from strandbeest_common.migrate import migrate_doc
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design
from strandbeest_sim.builder import build, build_herd, resolve_spec
from strandbeest_sim.config import sim_config

DESIGN = Design.load(schema_dir() / "examples/design-jansen-small-6leg.json")


def references(body_mass, ratio, stiffness=40000.0):
    sc = scenario_from_design(DESIGN, {"walker": {"body_mass": body_mass},
                                     "solver": {"contact_stiffness": stiffness,
                                                "contact_damping_ratio": ratio}})
    solo = build(sc, resolve_spec(sc))
    herd = build_herd(sc)
    return sc, [tuple(map(float, ElementTree.fromstring(b.xml).find("default/geom").attrib["solref"].split()))
                for b in (solo, herd)]


def contact_model(reference, mass):
    # A single vertical degree of freedom; constant impedance cancels its
    # scaling in the effective acceleration. No gravity, friction or contacts
    # other than this sphere/plane. Initial contact force stays compressive.
    xml = f'''<mujoco><option timestep="0.00001" gravity="0 0 0" solver="Newton" tolerance="1e-12"/>
      <default><geom solref="{reference[0]} {reference[1]}" solimp="0.9 0.9 0.001 0.5 2" condim="1"/></default>
      <worldbody><geom type="plane" size="1 1 .1"/>
        <body pos="0 0 .048"><joint type="slide" axis="0 0 1"/>
          <geom type="sphere" size=".05" mass="{mass}"/>
        </body></worldbody></mujoco>'''
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    data.qvel[0] = .01
    mujoco.mj_forward(model, data)
    assert data.ncon == 1
    return model, data


@pytest.mark.parametrize("body_mass", [.05, .5, 50.0])
@pytest.mark.parametrize("ratio", [.5, 1.0, 2.0])
def test_native_contact_obeys_requested_damping_ratio_independently_of_walker_mass(body_mass, ratio):
    stiffness = 40000.0
    _, refs = references(body_mass, ratio, stiffness)
    for ref in refs:
        for probe_mass in (.02, 2.0):
            _, data = contact_model(ref, probe_mass)
            # x'' + 2*zeta*sqrt(k)*x' + k*x = 0, with x=-.002m.
            expected_acceleration = stiffness * .002 - 2 * ratio * math.sqrt(stiffness) * .01
            assert data.qacc[0] == pytest.approx(expected_acceleration, abs=2e-10)


@pytest.mark.parametrize("ratio", [.5, 1., 2.])
def test_builder_direct_format_matches_native_positive_format_trajectory(ratio):
    stiffness = 40000.0
    _, refs = references(.35, ratio, stiffness)
    direct_model, direct_data = contact_model(refs[0], .7)
    positive_model, positive_data = contact_model((1 / (ratio * math.sqrt(stiffness)), ratio), .7)
    for _ in range(200):
        mujoco.mj_step(direct_model, direct_data)
        mujoco.mj_step(positive_model, positive_data)
        np.testing.assert_allclose(direct_data.qpos, positive_data.qpos, rtol=0, atol=2e-14)
        np.testing.assert_allclose(direct_data.qvel, positive_data.qvel, rtol=0, atol=2e-12)


def test_single_walker_and_herd_builders_share_the_contact_contract():
    sc, refs = references(.35, 1.)
    assert refs[0] == refs[1]
    doc = sc.model_dump(mode="json", exclude_unset=True)
    another = copy.deepcopy(doc["entities"][0])
    another["name"] = "distant-heavier-walker"
    another["placement"] = {"x": 0., "y": 10., "phase_offset": 0.}
    another["components"]["body"]["body_mass"] = 40.
    doc["entities"].append(another)
    ref = ElementTree.fromstring(build_herd(doc).xml).find("default/geom").attrib["solref"]
    assert tuple(map(float, ref.split())) == refs[0]


def test_actual_solo_and_single_entity_herd_settle_identically():
    sc, _ = references(.35, 1.)
    models = [mujoco.MjModel.from_xml_string(b.xml) for b in (build(sc, resolve_spec(sc)), build_herd(sc))]
    states = [mujoco.MjData(m) for m in models]
    for _ in range(500):
        for model, data in zip(models, states):
            mujoco.mj_step(model, data)
    np.testing.assert_allclose(states[0].qpos, states[1].qpos, rtol=0, atol=1e-12)
    np.testing.assert_allclose(states[0].qvel, states[1].qvel, rtol=0, atol=1e-10)


def test_positive_time_constant_fallback_and_scenario_roundtrip_are_preserved():
    sc = scenario_from_design(DESIGN, {"solver": {"contact_stiffness": None, "contact_solref": .015}})
    for result in (build(sc, resolve_spec(sc)), build_herd(sc)):
        assert ElementTree.fromstring(result.xml).find("default/geom").attrib["solref"] == "0.015 1"
    flat = sim_config(sc).model_dump(mode="json", exclude_unset=True)
    migrated = migrate_doc("scenario", flat)
    Draft202012Validator(json.loads((schema_dir() / "scenario.schema.json").read_text())).validate(migrated)
    assert sim_config(migrated).solver == sim_config(sc).solver
