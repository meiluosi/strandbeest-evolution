import json
from pathlib import Path

import pytest

from strandbeest_common import Design, solve_pose, validate
from strandbeest_common.schemas import schema_dir

EX = schema_dir() / "examples"


@pytest.mark.parametrize("name", ["design", "measurement", "profile", "run"])
def test_examples_validate(name):
    for f in EX.glob(f"{name}-*.json"):
        validate(name, json.loads(f.read_text()))


def test_design_rejects_unknown_field_and_bad_value():
    d = json.loads((EX / "design-jansen-small-6leg.json").read_text())
    d["walker"]["legz"] = 3
    with pytest.raises(ValueError, match="legz"):
        validate("design", d)
    d = json.loads((EX / "design-jansen-small-6leg.json").read_text())
    d["manufacturing"]["clearance_mm"] = -0.1
    with pytest.raises(ValueError, match="clearance_mm"):
        validate("design", d)


def test_design_loads_and_its_linkage_assembles():
    d = Design.load(EX / "design-jansen-small-6leg.json")
    assert solve_pose(d.spec, 0.4) is not None
    assert 0.01 < d.bar_mass_per_m() < 0.1  # kg/m for a 10x3 mm printed bar
