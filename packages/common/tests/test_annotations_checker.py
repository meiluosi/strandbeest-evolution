import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_schema_annotations.py"


def run(schema, tmp_path, *flags):
    p = tmp_path / "x.schema.json"
    p.write_text(json.dumps(schema))
    return subprocess.run([sys.executable, str(SCRIPT), *flags, str(p)], capture_output=True, text=True)


def test_flags_numeric_fields_without_a_unit_and_passes_when_annotated(tmp_path):
    bad = {"type": "object", "properties": {"length": {"type": "number"}}}
    r = run(bad, tmp_path, "--strict")
    assert r.returncode == 1 and "length: numeric field without x-unit" in r.stdout
    good = {"type": "object", "properties": {"length": {"type": "number", "x-unit": "m"}}}
    assert run(good, tmp_path, "--strict").returncode == 0


def test_warn_mode_does_not_fail_and_assumptions_need_a_source(tmp_path):
    bad = {"type": "object", "properties": {"mu": {"type": "number", "x-unit": "1", "x-assumption": True}}}
    assert run(bad, tmp_path).returncode == 0
    r = run(bad, tmp_path, "--strict")
    assert r.returncode == 1 and "x-assumption without x-source" in r.stdout


def test_const_and_enum_numbers_are_exempt(tmp_path):
    ok = {"type": "object", "properties": {"schema_version": {"const": 1}, "direction": {"enum": [-1, 1]}}}
    assert run(ok, tmp_path, "--strict").returncode == 0
