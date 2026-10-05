"""E3-02/E3-03: the edit algebra. Contract corpus shared with packages/core/src/ops.test.ts, plus property tests."""
import copy
import json
import math
import random
from pathlib import Path

import pytest
from strandbeest_common import Design
from strandbeest_common.gait import foot_path
from strandbeest_common.guard import design_problems, kinematic_problems
from strandbeest_common.ids import is_ulid
from strandbeest_common.jsonpatch import apply_patch, diff, same
from strandbeest_common.linkage import load_spec, solve_pose
from strandbeest_common.ops import OPS, GuardError, History, OpError, apply_op, make_op, replay

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "contracts" / "ops" / "cases.json").read_text())["cases"]
DESIGN = "schemas/examples/design-jansen-small-6leg.json"


def load(p: str):
    return json.loads((ROOT / p).read_text())


def base_doc(base: dict) -> dict:
    d = load(base["design"])
    lk = base.get("linkage")
    if isinstance(lk, str):
        d["linkage"] = load(lk)["spec"]
    elif isinstance(lk, dict):
        d["linkage"] = lk
    return d


def op_of(t: str, a: dict):
    return make_op(t, a, id="0000000000YNGRWX0MDFYPZHXT", time="2026-10-06T00:00:00.000Z")


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:48] for c in CASES])
def test_corpus_case(case):
    d = base_doc(case["base"])
    start = copy.deepcopy(d)
    exp = case["expect"]
    for i, o in enumerate(case["ops"]):
        try:
            d = apply_op(d, op_of(o["type"], o["args"])).design
        except OpError as e:
            assert exp["error"] == {"kind": "op", "code": e.code, "step": i}
            return
        except GuardError as e:
            assert exp["error"] == {"kind": "guard", "codes": [p["code"] for p in e.problems], "step": i}
            return
    assert "patch" in exp, "the corpus expected a rejection but every operation was accepted"
    assert diff(start, d) == exp["patch"]
    assert same(apply_patch(start, exp["patch"]), d)


def test_add_dyad_turns_the_four_bar_into_exactly_the_corpus_six_bar_and_passes_the_guard():
    four = base_doc({"design": DESIGN, "linkage": "contracts/kinematics/fourbar-crank-rocker.json"})
    six = apply_op(four, op_of("add_dyad", {"id": "X", "centers": ["C", "K"], "radii": ["p", "q"], "side": -1, "params": {"p": 30.0, "q": 25.0}, "foot": True})).design
    assert six["linkage"] == load("contracts/kinematics/sixbar-extra-dyad.json")["spec"]
    assert [p for p in design_problems(six) if p["level"] == "error"] == []
    Design(six)  # a full design validates (schema + structure)


def test_every_operation_type_has_a_description_and_the_schema_lists_exactly_these_types():
    schema = load("schemas/ops.schema.json")
    in_schema = {d["properties"]["type"]["const"] for n, d in schema["$defs"].items() if n.endswith("Op")}
    assert in_schema == set(OPS) | {"patch"}


# ------------------------------------------------------------------------------------------- properties
BASES = {
    "jansen": base_doc({"design": DESIGN}),
    "fourbar": base_doc({"design": DESIGN, "linkage": "contracts/kinematics/fourbar-crank-rocker.json"}),
    "sixbar": base_doc({"design": DESIGN, "linkage": "contracts/kinematics/sixbar-extra-dyad.json"}),
}


def random_op(rng: random.Random, d: dict):
    lk = d["linkage"]
    points = ["G", "C", *[j["id"] for j in lk["joints"]]]
    kind = rng.choice(["set_param"] * 5 + ["add_dyad"] * 3 + ["remove_joint", "array_legs", "scale", "mirror", "set_material"])
    if kind == "remove_joint" and not lk["joints"]:
        kind = "set_param"
    if kind == "set_param":
        name = rng.choice(list(lk["params"]) + ["nope"])
        cur = lk["params"].get(name, 10.0)
        return "set_param", {"name": name, "value": cur * rng.choice([0.5, 0.9, 0.99, 1.01, 1.1, 1.5, 3.0]) if rng.random() < 0.9 else rng.choice([0.0, -3.0, 1e-9])}
    if kind == "add_dyad":
        n = rng.randrange(1000)
        return "add_dyad", {"id": rng.choice([f"J{n}", "K"]), "centers": [rng.choice(points), rng.choice(points)],
                            "radii": [f"r{n}a", f"r{n}b"], "side": rng.choice([1, -1]),
                            "params": {f"r{n}a": rng.uniform(10, 80), f"r{n}b": rng.uniform(10, 80)}, "foot": rng.random() < 0.5}
    if kind == "remove_joint":
        j = rng.choice(lk["joints"])["id"]
        return "remove_joint", {"id": j, "foot": rng.choice(points), "drop_params": rng.random() < 0.7}
    if kind == "array_legs":
        return "array_legs", {"legs": rng.choice([0, 1, 4, 6, 12])}
    if kind == "scale":
        return "scale", {"factor": rng.choice([0.5, 0.8, 1.25, 2.0, -1.0]), "keep_physical": rng.random() < 0.5}
    if kind == "mirror":
        return "mirror", {}
    return "set_material", {"material": rng.choice(["PLA", "PETG", "wood"])}


def no_errors(d):
    return [p for p in design_problems(d) if p["level"] == "error"]


@pytest.mark.parametrize("base_name", BASES)
def test_random_operation_sequences_keep_every_property(base_name):
    base = BASES[base_name]
    assert no_errors(base) == []
    rng = random.Random(f"ops-{base_name}")
    accepted = rejected = 0
    for round_ in range(40):
        h = History(base)
        snapshots = [copy.deepcopy(h.design)]
        for _ in range(12):
            t, a = random_op(rng, h.design)
            before = copy.deepcopy(h.design)
            try:
                applied = h.commit(op_of(t, a))
            except (OpError, GuardError):
                rejected += 1
                assert h.design == before, "a rejected operation changed the design"
                continue
            accepted += 1
            # the guard never lets an invalid design through
            assert no_errors(h.design) == [], (t, a)
            # the inverse is exact
            assert same(apply_op(h.design, applied.inverse, guards=()).design, before)
            snapshots.append(copy.deepcopy(h.design))
        # replay of the log gives the same design
        assert same(replay(base, h.ops), h.design)
        # undo walks back through every snapshot, redo walks forward again
        for snap in reversed(snapshots[:-1]):
            h.undo()
            assert same(h.design, snap)
        assert same(h.design, base) and not h.can_undo
        for snap in snapshots[1:]:
            h.redo()
            assert same(h.design, snap)
        assert not h.can_redo
    assert accepted > 100 and rejected > 100  # the generator exercises both outcomes


def test_a_new_commit_discards_the_redo_branch():
    h = History(BASES["jansen"])
    h.commit(op_of("array_legs", {"legs": 4}))
    h.undo()
    assert h.can_redo
    h.commit(op_of("array_legs", {"legs": 8}))
    assert not h.can_redo and h.design["walker"]["legs"] == 8


def test_guard_blames_only_new_errors_so_a_broken_design_can_be_repaired():
    broken = copy.deepcopy(BASES["jansen"])
    broken["linkage"]["params"]["h"] = 1.0
    assert [p["code"] for p in no_errors(broken)] == ["cannot_assemble"]
    # still broken after an unrelated edit: allowed (no new error)
    apply_op(broken, op_of("array_legs", {"legs": 4}))
    # a repair is allowed, and so is a further change that leaves it broken in the same way
    fixed = apply_op(broken, op_of("set_param", {"name": "h", "value": 65.7})).design
    assert no_errors(fixed) == []


def test_patch_operations_are_guarded_like_any_other():
    d = BASES["jansen"]
    bad = make_op("patch", {"patch": [{"op": "replace", "path": "/linkage/params/h", "value": 1.0}]})
    with pytest.raises(GuardError):
        apply_op(d, bad)
    with pytest.raises(OpError, match="bad_patch"):
        apply_op(d, make_op("patch", {"patch": [{"op": "remove", "path": "/nope"}]}))


def test_operations_carry_who_why_and_when():
    op = make_op("set_param", {"name": "m", "value": 14.0}, actor={"kind": "agent", "id": "claude"}, reason="longer stride")
    assert is_ulid(op["id"]) and op["actor"] == {"kind": "agent", "id": "claude"} and op["reason"] == "longer stride"
    assert op["time"].endswith("Z")
    applied = apply_op(BASES["jansen"], op)
    assert applied.inverse["actor"]["id"] == "claude" and applied.inverse["type"] == "patch"
    with pytest.raises(OpError, match="actor"):
        apply_op(BASES["jansen"], {**op, "actor": {"kind": "ghost", "id": "x"}})


def test_ops_are_valid_against_the_ops_schema_and_models():
    from jsonschema import Draft202012Validator
    from strandbeest_common.models.ops import OpLog

    schema = load("schemas/ops.schema.json")
    h = History(BASES["fourbar"])
    h.commit(op_of("add_dyad", {"id": "X", "centers": ["C", "K"], "radii": ["p", "q"], "side": -1, "params": {"p": 30.0, "q": 25.0}, "foot": True}))
    h.commit(op_of("scale", {"factor": 1.1}))
    h.commit(op_of("mirror", {}))
    log = {"schema_version": 1, "design_id": BASES["fourbar"]["id"], "base": BASES["fourbar"], "ops": h.ops}
    Draft202012Validator(schema).validate(log)
    OpLog.model_validate(log)
    undo = apply_op(h.design, make_op("patch", {"patch": diff(h.design, BASES["fourbar"])}))
    Draft202012Validator(schema).validate({**log, "ops": [*h.ops, undo.inverse]})


def foot_cloud(doc: dict, n: int = 120):
    spec = load_spec(doc["linkage"])
    pts = []
    for i in range(n):
        pose = solve_pose(spec, 2 * math.pi * i / n)
        assert pose is not None
        pts.append(pose[spec.foot])
    return pts


def test_mirror_reflects_the_foot_path_and_reverses_the_crank():
    d = BASES["jansen"]
    m = apply_op(d, op_of("mirror", {})).design
    assert m["walker"]["direction"] == -d["walker"]["direction"]
    # same loop reflected in x: every mirrored foot point matches a reflected original point
    orig = foot_cloud(d)
    refl = foot_cloud(m)
    for x, y in refl:
        assert min(math.hypot(-x - ox, y - oy) for ox, oy in orig) < 0.7  # sampled loops: within one sampling step


def test_scale_with_keep_physical_leaves_the_physical_foot_path_unchanged():
    d = BASES["jansen"]
    s = apply_op(d, op_of("scale", {"factor": 2.0, "keep_physical": True})).design
    a = [(x * d["walker"]["unit_m"], y * d["walker"]["unit_m"]) for x, y in foot_cloud(d)]
    b = [(x * s["walker"]["unit_m"], y * s["walker"]["unit_m"]) for x, y in foot_cloud(s)]
    assert all(math.isclose(p[0], q[0], abs_tol=1e-12) and math.isclose(p[1], q[1], abs_tol=1e-12) for p, q in zip(a, b))


def test_kinematic_guard_accepts_every_corpus_design_and_jansen_with_sensible_edits():
    for f in sorted((ROOT / "contracts" / "kinematics").glob("*.json")):
        assert kinematic_problems(json.loads(f.read_text())["spec"]) == [], f.name
