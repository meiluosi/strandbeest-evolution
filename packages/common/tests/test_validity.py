"""E3-01: static validity of linkage specs, shared with packages/core/src/validity.test.ts through the case corpus."""
import json
from pathlib import Path

import pytest
from strandbeest_common import Design
from strandbeest_common.validity import structure_errors

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "contracts" / "linkage-structure" / "cases.json").read_text())["cases"]
EXAMPLE = json.loads((ROOT / "schemas" / "examples" / "design-jansen-small-6leg.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:40] for c in CASES])
def test_corpus_case(case):
    got = [{"code": e["code"], "path": e["path"]} for e in structure_errors(case["spec"])]
    assert got == case["errors"]


def test_every_kinematics_contract_is_structurally_valid():
    for f in sorted((ROOT / "contracts" / "kinematics").glob("*.json")):
        assert structure_errors(json.loads(f.read_text())["spec"]) == [], f.name


def test_design_rejects_a_structurally_invalid_linkage_with_readable_messages():
    bad = json.loads(json.dumps(EXAMPLE))
    bad["linkage"]["joints"][0]["radii"][0] = "nope"
    with pytest.raises(ValueError, match="'nope' is not an entry of params"):
        Design(bad)


def test_design_accepts_a_zero_crank_pivot_coordinate():
    ok = json.loads(json.dumps(EXAMPLE))
    ok["linkage"]["params"]["l"] = 0.0
    Design(ok)
