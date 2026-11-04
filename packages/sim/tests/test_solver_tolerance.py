"""The persisted precision request must reach the actual backend, including zero."""

import copy
import json
import xml.etree.ElementTree as ET

import mujoco
import pytest

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import build_herd, load_scenario, scenario_from_design
from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.builder import build, resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.terrains import flat


DESIGN = Design.load(schema_dir() / "examples/design-jansen-small-6leg.json")


@pytest.mark.parametrize("tolerance", [None, 0.0, 1e-12, 1e-10])
@pytest.mark.parametrize("herd", [False, True])
def test_precision_survives_reload_and_reaches_compiled_model(tolerance, herd):
    scenario = scenario_from_design(DESIGN, {"solver": {"tolerance": tolerance}})
    saved = json.loads(scenario.model_dump_json(exclude_unset=True))
    reloaded = load_scenario(saved)
    assert reloaded == scenario
    assert saved["solver"]["tolerance"] == tolerance
    if herd:
        second = copy.deepcopy(saved["entities"][0])
        second["name"] = "second"
        saved["entities"].append(second)
        built = build_herd(saved)
    else:
        cfg = sim_config(reloaded)
        built = build(cfg, resolve_spec(cfg))
    option = ET.fromstring(built.xml).find("option")
    assert option is not None
    if tolerance is None:
        assert "tolerance" not in option.attrib
    else:
        assert float(option.attrib["tolerance"]) == tolerance
    model = mujoco.MjModel.from_xml_string(built.xml)
    assert model.opt.tolerance == (1e-8 if tolerance is None else tolerance)


@pytest.mark.parametrize("tolerance", [-1.0, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("herd", [False, True])
def test_invalid_precision_cannot_build(tolerance, herd):
    saved = scenario_from_design(DESIGN).model_dump(mode="json", exclude_unset=True)
    saved["solver"]["tolerance"] = tolerance
    with pytest.raises(ValueError, match="tolerance"):
        if herd:
            build_herd(saved)
        else:
            cfg = sim_config(load_scenario(saved))
            build(cfg, resolve_spec(cfg))


@pytest.mark.parametrize("tolerance", [0.0, 1e-12])
def test_k2_rejects_unsupported_explicit_precision(tolerance):
    cfg = sim_config(scenario_from_design(DESIGN, {"solver": {"tolerance": tolerance}}))
    with pytest.raises(ValueError, match="solver.tolerance.*MuJoCo"):
        K2Backend().build(cfg, flat(cfg))
