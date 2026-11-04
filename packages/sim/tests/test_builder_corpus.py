"""Keep the shared browser fixture tied to the current Python builder source."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "generate_sim_mjcf", ROOT / "contracts/generate_sim_mjcf.py"
)
assert SPEC and SPEC.loader
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)
CORPUS = json.loads((ROOT / "contracts/sim-mjcf/cases-contact-v3.json").read_text())


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["name"])
def test_current_python_builder_matches_browser_corpus(case):
    actual = GENERATOR.run_case(CORPUS["designs"][case["design"]], case["overrides"])
    expected = case["expected"]
    if "error" in expected:
        assert "error" in actual
    else:
        assert actual == expected
