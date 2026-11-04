"""A retained, untraceable comparison must not promote itself to external evidence."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "verify_literature", ROOT / "scripts/verify_literature_kinematics.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_unverified_source_blocks_default_validation(capsys, monkeypatch):
    def must_not_solve(*args):
        raise AssertionError("Source eligibility must be checked before numerical comparison")

    monkeypatch.setattr(MODULE, "solve_analytical_foot_path", must_not_solve)
    assert MODULE.main([]) == 2
    assert "NOT VERIFIED" in capsys.readouterr().out


def test_even_exact_legacy_match_does_not_grant_evidence(capsys, monkeypatch):
    legacy = json.loads((ROOT / "experiments/literature-jansen-amm2014.json").read_text())
    monkeypatch.setattr(MODULE, "solve_analytical_foot_path", lambda _: legacy["points_24"])
    assert MODULE.main(["--unverified-preview"]) == 0
    output = capsys.readouterr().out
    assert "UNVERIFIED PREVIEW" in output
    assert "no evidence upgrade is granted" in output
    assert "Verification PASSED" not in output
    assert "elevated" not in output
