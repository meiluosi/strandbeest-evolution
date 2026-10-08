"""E4-01: scenario schema v1 (flat) <-> v2 (World + Entities)."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from strandbeest_common.migrate import detect_kind, migrate_any
from strandbeest_common.models.scenario import Scenario
from strandbeest_common.models.scenario_v1 import ScenarioV1
from strandbeest_common.scenario import flatten, to_v2

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = json.loads((ROOT / "contracts" / "sim-golden" / "runs.json").read_text())["runs"]
V2 = Draft202012Validator(json.loads((ROOT / "schemas" / "scenario.schema.json").read_text()))


@pytest.mark.parametrize("g", GOLDEN, ids=[g["name"] for g in GOLDEN])
def test_round_trip_is_lossless_and_the_v2_document_validates(g):
    v1 = ScenarioV1.model_validate(g["scenario"]).model_dump(mode="json")
    v2 = to_v2(g["scenario"])
    V2.validate(v2)
    Scenario.model_validate(v2)
    assert ScenarioV1.model_validate(flatten(v2)).model_dump(mode="json") == v1
    assert to_v2(flatten(v2)) == v2


def test_world_and_entity_structure():
    v2 = to_v2({"environment": {"gravity": 3.7, "air_density": 0.02}, "terrain": {"kind": "slope", "slope_deg": 5}, "wind": {"speed": 2.0}})
    assert v2["schema_version"] == 2
    assert v2["world"]["gravity"] == 3.7 and v2["world"]["atmosphere"] == {"air_density": 0.02}
    assert v2["world"]["terrain"]["kind"] == "slope" and v2["world"]["wind"]["speed"] == 2.0
    (e,) = v2["entities"]
    assert e["name"] == "walker" and e["kind"] == "walker" and set(e["components"]) == {"linkage", "body", "drive"}


def test_flatten_refuses_what_the_simulator_cannot_run_yet():
    v2 = to_v2({})
    two = {**v2, "entities": [v2["entities"][0], {**v2["entities"][0], "name": "second"}]}
    with pytest.raises(ValueError, match="one walker"):
        flatten(two)
    missing = {**v2, "entities": [{**v2["entities"][0], "components": {"linkage": {}, "body": {}}}]}
    with pytest.raises(ValueError, match="drive"):
        flatten(missing)


def test_migrate_any_recognises_and_upgrades_a_flat_scenario():
    flat = {"schema_version": 1, "name": "x", "walker": {"legs": 4}, "terrain": {"kind": "flat"}, "solver": {}}
    assert detect_kind(flat) == "scenario"
    v2 = migrate_any(flat)
    assert v2["entities"][0]["components"]["body"]["legs"] == 4 and v2["name"] == "x"
    assert migrate_any(v2) == v2  # already v2
    assert detect_kind(v2) == "scenario"
