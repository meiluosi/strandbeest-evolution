#!/usr/bin/env python3
"""Regenerate contracts/ops/cases.json from the Python implementation of the edit algebra.

Each case applies a list of operations to a base design and records either the exact JSON patch from base to result,
or the error the operation must be rejected with. The TypeScript runner must produce the same patches and the same
rejections; that is what keeps the two implementations of the algebra from drifting (ADR-0009)."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/common/src"))
from strandbeest_common.jsonpatch import diff  # noqa: E402
from strandbeest_common.ops import GuardError, OpError, apply_op, make_op  # noqa: E402

DESIGN = "schemas/examples/design-jansen-small-6leg.json"
FOURBAR = "contracts/kinematics/fourbar-crank-rocker.json"
SIXBAR = "contracts/kinematics/sixbar-extra-dyad.json"


def load(p):
    return json.loads((ROOT / p).read_text())


def base_doc(base):
    d = load(base["design"])
    lk = base.get("linkage")
    if isinstance(lk, str):
        d["linkage"] = load(lk)["spec"]
    elif isinstance(lk, dict):
        d["linkage"] = lk
    return d


JANSEN = {"design": DESIGN}
FOUR = {"design": DESIGN, "linkage": FOURBAR}
SIX = {"design": DESIGN, "linkage": SIXBAR}
SHARED_PIVOT = copy.deepcopy(load(FOURBAR)["spec"])
SHARED_PIVOT["joints"][0]["radii"][1] = "a"  # crank.x's param is also a bar length
OFFSET_PIVOT = copy.deepcopy(load(FOURBAR)["spec"])
OFFSET_PIVOT["params"]["l"] = 3.0  # the pivot is off the symmetry axis, so a narrow failing window falls between two samples
ADD_X = {"id": "X", "centers": ["C", "K"], "radii": ["p", "q"], "side": -1, "params": {"p": 30.0, "q": 25.0}, "foot": True}

CASES = [
    ("set_param changes one length", JANSEN, [("set_param", {"name": "m", "value": 14.0})]),
    ("set_param on an unknown name", JANSEN, [("set_param", {"name": "zz", "value": 1.0})]),
    ("set_param with a non-number", JANSEN, [("set_param", {"name": "m", "value": "long"})]),
    ("set_param that cannot assemble", JANSEN, [("set_param", {"name": "h", "value": 1.0})]),
    ("set_param near the crank limit: fast but continuous, accepted", FOUR, [("set_param", {"name": "m", "value": 31.0})]),
    ("set_param into a window too narrow for the samples is a branch flip", {"design": DESIGN, "linkage": OFFSET_PIVOT}, [("set_param", {"name": "m", "value": 33.12})]),
    ("set_param beyond the crank limit cannot assemble", FOUR, [("set_param", {"name": "m", "value": 34.0})]),
    ("add_dyad turns the four-bar into the six-bar", FOUR, [("add_dyad", ADD_X)]),
    ("add_dyad with an existing joint id", FOUR, [("add_dyad", {**ADD_X, "id": "K"})]),
    ("add_dyad with an existing param name", FOUR, [("add_dyad", {**ADD_X, "params": {"p": 30.0, "b": 1.0}})]),
    ("add_dyad centred on an unknown point", FOUR, [("add_dyad", {**ADD_X, "centers": ["C", "Q"]})]),
    ("add_dyad with a bad side", FOUR, [("add_dyad", {**ADD_X, "side": 0})]),
    ("add_dyad that cannot assemble", FOUR, [("add_dyad", {**ADD_X, "params": {"p": 1.0, "q": 1.0}})]),
    ("add_dyad with inline lengths and not the foot", FOUR, [("add_dyad", {"id": "X", "centers": ["C", "K"], "radii": [30.0, 25.0], "side": -1})]),
    ("remove_joint of the foot needs a new foot", SIX, [("remove_joint", {"id": "X"})]),
    ("remove_joint of the foot with a new foot", SIX, [("remove_joint", {"id": "X", "foot": "K"})]),
    ("remove_joint of a joint others are built on", SIX, [("remove_joint", {"id": "K", "foot": "X"})]),
    ("remove_joint keeping the unused params", SIX, [("remove_joint", {"id": "X", "foot": "K", "drop_params": False})]),
    ("remove_joint of an unknown joint", SIX, [("remove_joint", {"id": "Q"})]),
    ("add_dyad then remove_joint is the identity", FOUR, [("add_dyad", ADD_X), ("remove_joint", {"id": "X", "foot": "K"})]),
    ("set_length edits a named length like set_param", JANSEN, [("set_length", {"key": "m", "value": 14.0})]),
    ("set_length edits an inline bar length", FOUR, [("add_dyad", {"id": "X", "centers": ["C", "K"], "radii": [30.0, 25.0], "side": -1, "foot": True}), ("set_length", {"key": "joint:X.radii.0", "value": 32.0})]),
    ("set_length on a named bar says to set the param", FOUR, [("set_length", {"key": "joint:K.radii.0", "value": 40.0})]),
    ("set_length on the named crank pivot says to set the param", FOUR, [("set_length", {"key": "crank.x", "value": 41.0})]),
    ("set_length on an unknown handle", FOUR, [("set_length", {"key": "joint:Q.radii.0", "value": 1.0})]),
    ("set_length that cannot assemble", FOUR, [("add_dyad", {"id": "X", "centers": ["C", "K"], "radii": [30.0, 25.0], "side": -1, "foot": True}), ("set_length", {"key": "joint:X.radii.0", "value": 1.0})]),
    ("set_property changes the leg count", JANSEN, [("set_property", {"path": "/walker/legs", "value": 4})]),
    ("set_property below the schema minimum", JANSEN, [("set_property", {"path": "/walker/legs", "value": 0})]),
    ("set_property with the wrong kind of value", JANSEN, [("set_property", {"path": "/walker/legs", "value": "four"})]),
    ("set_property renames the design", JANSEN, [("set_property", {"path": "/name", "value": "my walker"})]),
    ("set_property of the name to a number", JANSEN, [("set_property", {"path": "/name", "value": 5})]),
    ("set_property of the linkage is not allowed", JANSEN, [("set_property", {"path": "/linkage/foot", "value": "K"})]),
    ("set_property of the id is not allowed", JANSEN, [("set_property", {"path": "/id", "value": "x"})]),
    ("set_property of a property that does not exist", JANSEN, [("set_property", {"path": "/walker/tail", "value": 1})]),
    ("set_property of a negative spacing", JANSEN, [("set_property", {"path": "/walker/lateral_spacing_m", "value": -1})]),
    ("set_property of an enum to an unknown member", JANSEN, [("set_property", {"path": "/drive/kind", "value": "wind"})]),
    ("set_property of an enum to another member", JANSEN, [("set_property", {"path": "/drive/kind", "value": "sail"})]),
    ("set_property of an array with the wrong length", JANSEN, [("set_property", {"path": "/manufacturing/bed_mm", "value": [100]})]),
    ("set_property of an array", JANSEN, [("set_property", {"path": "/manufacturing/bed_mm", "value": [100, 120]})]),
    ("set_property with a pointer that is not a pointer", JANSEN, [("set_property", {"path": "walker/legs", "value": 4})]),
    ("array_legs sets the leg count", JANSEN, [("array_legs", {"legs": 8})]),
    ("array_legs below one", JANSEN, [("array_legs", {"legs": 0})]),
    ("array_legs with a non-integer", JANSEN, [("array_legs", {"legs": 2.5})]),
    ("scale multiplies every length", JANSEN, [("scale", {"factor": 1.5})]),
    ("scale keeping the physical size changes the unit", JANSEN, [("scale", {"factor": 2.0, "keep_physical": True})]),
    ("scale by a non-positive factor", JANSEN, [("scale", {"factor": 0})]),
    ("scale reaches inline lengths too", FOUR, [("add_dyad", {"id": "X", "centers": ["C", "K"], "radii": [30.0, 25.0], "side": -1, "foot": True}), ("scale", {"factor": 2.0})]),
    ("mirror reflects the leg and reverses the crank", JANSEN, [("mirror", {})]),
    ("mirror twice is the identity", JANSEN, [("mirror", {}), ("mirror", {})]),
    ("mirror when the crank pivot param is shared", {"design": DESIGN, "linkage": SHARED_PIVOT}, [("mirror", {})]),
    ("set_material", JANSEN, [("set_material", {"material": "PETG"})]),
    ("set_material with an unknown material", JANSEN, [("set_material", {"material": "wood"})]),
    ("an unknown operation type", JANSEN, [("explode", {})]),
    ("a sequence that is valid step by step", FOUR, [("set_param", {"name": "m", "value": 12.0}), ("add_dyad", ADD_X), ("array_legs", {"legs": 4}), ("set_material", {"material": "PETG"})]),
]


def run(base, steps):
    d = base_doc(base)
    start = copy.deepcopy(d)
    for i, (t, a) in enumerate(steps):
        op = make_op(t, a, id="0000000000YNGRWX0MDFYPZHXT", time="2026-10-06T00:00:00.000Z")
        try:
            d = apply_op(d, op).design
        except OpError as e:
            return {"error": {"kind": "op", "code": e.code, "step": i}}
        except GuardError as e:
            return {"error": {"kind": "guard", "codes": [p["code"] for p in e.problems], "step": i}}
    return {"patch": diff(start, d)}


cases = []
for name, base, steps in CASES:
    cases.append({"name": name, "base": base, "ops": [{"type": t, "args": a} for t, a in steps], "expect": run(base, steps)})
out = Path(__file__).with_name("cases.json")
out.write_text(json.dumps({"_doc": "Operation cases: apply ops to a base design; expect the exact patch from base to result, or the rejection. Both runners must agree. Regenerate with generate_cases.py.", "cases": cases}, indent=1) + "\n")
for c in cases:
    e = c["expect"]
    print(c["name"][:58].ljust(60), "ERR " + json.dumps(e["error"]) if "error" in e else f"patch of {len(e['patch'])} step(s)")
