"""E1-03: JSON Schema is the source of truth; pydantic models and TS types are generated from it."""
import copy
import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from strandbeest_common.models import design as design_models
from strandbeest_common.models import scenario as scenario_models

ROOT = Path(__file__).resolve().parents[3]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = load_script("gen_models")
annotations = load_script("check_schema_annotations")


def schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())


def test_generated_files_are_up_to_date():
    assert gen.main(["--check"]) == 0


def test_annotations_complete_for_design_and_scenario():
    for name in ("design", "scenario"):
        assert annotations.check(ROOT / "schemas" / f"{name}.schema.json") == []


def schema_defaults(node: dict, root: dict):
    """The document made only of schema defaults."""
    if "$ref" in node:
        node = {**root["$defs"][node["$ref"].split("/")[-1]], **{k: v for k, v in node.items() if k != "$ref"}}
    if node.get("type") == "object" and "properties" in node:
        out = {}
        for k, sub in node["properties"].items():
            if "default" in sub and not (sub["default"] == {} and "$ref" in sub):
                out[k] = copy.deepcopy(sub["default"])
            elif "$ref" in sub:
                out[k] = schema_defaults(sub, root)
        return out
    return node.get("default")


def test_model_defaults_equal_schema_defaults_and_validate():
    s = schema("scenario")
    doc = schema_defaults(s, s)
    Draft202012Validator(s).validate(doc)
    assert scenario_models.Scenario.model_validate(doc) == scenario_models.Scenario()
    # and the model's own dump is a valid document
    Draft202012Validator(s).validate(scenario_models.Scenario().model_dump(mode="json"))


MUTATIONS = [0, -1, 1, 0.0001, 3.5, "x", None, [], {}, [1], {"a": 1}, "__del__", "jansen"]


def paths(d, p=()):
    yield p
    if isinstance(d, dict):
        for k, v in d.items():
            yield from paths(v, p + (k,))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            yield from paths(v, p + (i,))


def set_path(d, p, v):
    for k in p[:-1]:
        d = d[k]
    if v == "__del__":
        d.pop(p[-1], None) if isinstance(d, dict) else None
    else:
        d[p[-1]] = v


@pytest.mark.parametrize("name,models,base_file", [
    ("scenario", scenario_models.Scenario, None),
    ("design", design_models.Design, "design-jansen-small-6leg.json"),
])
def test_pydantic_and_json_schema_agree(name, models, base_file):
    s = schema(name)
    validator = Draft202012Validator(s)
    base = json.loads((ROOT / "schemas" / "examples" / base_file).read_text()) if base_file else schema_defaults(s, s)
    assert validator.is_valid(base)
    models.model_validate(base)
    ps = [p for p in paths(base) if p]
    rng = random.Random(7)
    disagreements = []
    for _ in range(1500):
        doc = copy.deepcopy(base)
        for _ in range(rng.randint(1, 3)):
            try:
                set_path(doc, rng.choice(ps), rng.choice(MUTATIONS))
            except (KeyError, IndexError, TypeError):
                pass
        schema_ok = validator.is_valid(doc)
        try:
            models.model_validate(doc)
            model_ok = True
        except ValidationError:
            model_ok = False
        if schema_ok != model_ok:
            disagreements.append((doc, schema_ok, model_ok))
    assert not disagreements, disagreements[:2]


def test_example_design_round_trips_through_generated_model():
    doc = json.loads((ROOT / "schemas" / "examples" / "design-jansen-small-6leg.json").read_text())
    model = design_models.Design.model_validate(doc)
    out = model.model_dump(mode="json", exclude_none=True)
    assert out == doc


def test_schema_change_changes_both_languages(tmp_path):
    """Add one field to the scenario schema in a scratch copy: the Python and TypeScript outputs both gain it."""
    sdir = tmp_path / "schemas"
    sdir.mkdir()
    for name in ("design", "scenario"):
        s = schema(name)
        if name == "scenario":
            s["$defs"]["Walker"]["properties"]["tail_length"] = {
                "type": "number", "minimum": 0, "default": 0.5,
                "x-unit": "m", "x-doc": {"zh": "尾巴长度", "en": "Tail length"},
            }
        (sdir / f"{name}.schema.json").write_text(json.dumps(s))
    py, ts = tmp_path / "py", tmp_path / "ts"
    assert gen.main(["--schemas", str(sdir), "--py-out", str(py), "--ts-out", str(ts)]) == 0
    assert "tail_length: float = Field(default=0.5, ge=0, description='Tail length')" in (py / "scenario.py").read_text()
    assert "tail_length?: number;" in (ts / "scenario.ts").read_text()
    # the checked-in files are now stale relative to that schema
    assert gen.main(["--check", "--schemas", str(sdir)]) == 1


def test_generator_rejects_unsupported_keywords(tmp_path):
    sdir = tmp_path / "schemas"
    sdir.mkdir()
    for name in ("design", "scenario"):
        s = schema(name)
        if name == "design":
            s["$defs"]["Walker"]["properties"]["legs"]["multipleOf"] = 2
        (sdir / f"{name}.schema.json").write_text(json.dumps(s))
    with pytest.raises(SystemExit, match="multipleOf"):
        gen.main(["--schemas", str(sdir), "--py-out", str(tmp_path / "p"), "--ts-out", str(tmp_path / "t")])
