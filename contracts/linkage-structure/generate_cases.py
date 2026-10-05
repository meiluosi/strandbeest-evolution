#!/usr/bin/env python3
"""Regenerate contracts/linkage-structure/cases.json from the Python implementation; the TypeScript runner must agree."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/common/src"))
from strandbeest_common.validity import structure_errors  # noqa: E402

BASE = {
    "params": {"a": 40, "l": 0, "m": 10, "b": 45, "j": 38},
    "crank": {"x": "a", "y": "l", "length": "m"},
    "joints": [{"id": "K", "centers": ["G", "C"], "radii": ["b", "j"], "side": 1}],
    "foot": "K",
}


def case(name, mutate=lambda s: None):
    s = copy.deepcopy(BASE)
    mutate(s)
    return {"name": name, "spec": s}


def forward(s):
    s["params"].update(p=30, q=25)
    s["joints"].insert(0, {"id": "X", "centers": ["C", "K"], "radii": ["p", "q"], "side": -1})
    s["foot"] = "X"


def several(s):
    s["crank"]["length"] = "missing"
    s["foot"] = "Z"


cases = [
    case("valid four-bar with the crank pivot at y=0 (zero is a legal coordinate)"),
    case("unknown param in a radius", lambda s: s["joints"][0]["radii"].__setitem__(0, "zz")),
    case("unknown param in the crank", lambda s: s["crank"].__setitem__("x", "nope")),
    case("unknown point as a circle centre", lambda s: s["joints"][0]["centers"].__setitem__(0, "Q")),
    case("forward reference: X uses K before K is solved", forward),
    case("duplicate joint id", lambda s: s["joints"].append({"id": "K", "centers": ["G", "C"], "radii": ["b", "j"], "side": -1})),
    case("reserved joint id", lambda s: s["joints"][0].__setitem__("id", "G")),
    case("unknown foot", lambda s: s.__setitem__("foot", "Z")),
    case("foot cannot be the ground", lambda s: s.__setitem__("foot", "G")),
    case("non-positive crank", lambda s: s["params"].__setitem__("m", 0)),
    case("negative bar via an inline number", lambda s: s["joints"][0]["radii"].__setitem__(1, -3)),
    case("both circles on one centre", lambda s: s["joints"][0].__setitem__("centers", ["G", "G"])),
    case("several problems at once, reported in a fixed order", several),
]
for c in cases:
    c["errors"] = [{"code": e["code"], "path": e["path"]} for e in structure_errors(c["spec"])]
out = Path(__file__).with_name("cases.json")
out.write_text(json.dumps({"_doc": "Expected static problems of linkage specs; both runners must report exactly these (code, path) pairs in this order.", "cases": cases}, indent=1) + "\n")
for c in cases:
    print(c["name"][:56].ljust(58), [e["code"] for e in c["errors"]])
