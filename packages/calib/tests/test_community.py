"""V-06: the community submission validator.

The acceptance criterion of the task card is that a stranger can follow docs/HOW-TO-MEASURE.md and
submit a Measurement that passes the check, so the bundled example is the reference here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from strandbeest_calib.community import (
    LICENCE_CHOICES,
    UNIT_CONTRACT,
    CommunityReport,
    validate_submission,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "schemas" / "examples"
EXAMPLE = EXAMPLES / "measurement-community-example.json"
DESIGN = EXAMPLES / "design-jansen-small-6leg.json"
GUIDE = ROOT / "docs" / "HOW-TO-MEASURE.md"
CLI = ROOT / "scripts" / "validate_community_measurement.py"


def example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def design() -> dict:
    return json.loads(DESIGN.read_text(encoding="utf-8"))


# --- the bundled example ----------------------------------------------------------------------


def test_the_bundled_example_is_a_valid_measurement():
    from strandbeest_common.schemas import validate

    validate("measurement", example())


def test_the_bundled_example_passes_with_a_clean_report():
    report = validate_submission(example(), design=design())
    assert report.ok, report.errors
    assert report.errors == []
    assert report.warnings == []
    assert report.evidence_level == "E3"
    assert report.e3_for, "the example should be able to support an evidence level"
    assert report.e3_gaps == []


def test_the_example_reports_what_is_missing():
    report = validate_submission(example(), design=design())
    # the example measured no wind, so the start-wind gap stays open
    assert any("wind" in item for item in report.missing)
    assert report.quality["revolutions"] >= 3.0
    assert report.quality["stride_m"] > 0.0


# --- broken submissions -----------------------------------------------------------------------


def broken() -> dict:
    """A submission with three defects: a missing required field, a wrong unit and a source-less provenance."""
    doc = example()
    del doc["name"]  # required by the schema
    doc["provenance"]["calibration"]["units"]["torque"] = "mN*m"  # the contract fixes this in N*m
    del doc["provenance"]["source"]  # a provenance record must say where the numbers came from
    return doc


def test_a_broken_submission_is_rejected_with_reasons():
    report = validate_submission(broken(), design=design())
    assert not report.ok
    assert report.errors, "a rejected submission must say why"
    joined = "\n".join(report.errors)
    assert "name" in joined, "the missing required field must be named"
    assert "mN*m" in joined, "the wrong unit must be named"
    assert "provenance/source" in joined, "the provenance record without a source must be named"
    # the reason is a path and a message, not a bare "invalid"
    for error in report.errors:
        assert len(error.split(":")) >= 2


def test_a_submission_without_psi_is_rejected():
    doc = example()
    del doc["channels"]["psi"]
    report = validate_submission(doc, design=design())
    assert not report.ok
    assert any("psi" in e for e in report.errors)


def test_a_submission_with_a_time_base_that_does_not_increase_is_rejected():
    doc = example()
    doc["channels"]["t"][5] = doc["channels"]["t"][4]
    report = validate_submission(doc, design=design())
    assert not report.ok
    assert any("channels/t" in e for e in report.errors)


def test_a_submission_with_channels_of_different_lengths_is_rejected():
    doc = example()
    doc["channels"]["torque"] = doc["channels"]["torque"][:-5]
    report = validate_submission(doc, design=design())
    assert not report.ok
    assert any("channels/torque" in e for e in report.errors)


def test_torque_in_the_wrong_unit_is_rejected_by_the_magnitude_check():
    doc = example()
    doc["channels"]["torque"] = [v * 10000.0 for v in doc["channels"]["torque"]]  # a raw count, not N*m
    report = validate_submission(doc, design=design())
    assert not report.ok
    assert any("channels/torque" in e for e in report.errors)


def test_a_stride_longer_than_the_leg_reach_is_suspicious():
    doc = example()
    doc["channels"]["x"] = [v * 20.0 for v in doc["channels"]["x"]]
    report = validate_submission(doc, design=design())
    assert report.ok, "an implausible stride is a warning, not a rejection"
    assert any("reach" in w for w in report.warnings)


def test_a_synthetic_record_cannot_support_an_evidence_level():
    doc = example()
    doc["synthetic"] = True
    report = validate_submission(doc, design=design())
    assert report.ok
    assert report.evidence_level == "E0"
    assert report.e3_for == []


# --- present but weak versus absent ------------------------------------------------------------


def test_the_report_separates_weak_data_from_absent_data():
    doc = example()
    del doc["provenance"]["calibration"]["uncertainty"]["torque"]  # recorded, but not with an error estimate
    report = validate_submission(doc, design=design())
    assert report.ok
    weak = [item for item in report.weak if "torque" in item]
    missing = [item for item in report.missing if "torque" in item]
    assert weak, "a torque channel without an error estimate is weak, not absent"
    assert not missing, "the torque channel is there, so it must not be reported as missing"
    assert any("wind" in item for item in report.missing), "the wind was never measured"
    assert "crank torque" not in " ".join(report.present)


def test_a_fully_documented_quantity_is_present():
    report = validate_submission(example(), design=design())
    assert any("torque" in item for item in report.present)
    assert not any("torque" in item for item in report.weak)
    assert not any("torque" in item for item in report.missing)


def test_a_quantity_without_a_declared_unit_is_weak():
    doc = example()
    del doc["provenance"]["calibration"]["units"]["x"]
    report = validate_submission(doc, design=design())
    assert report.ok
    assert any("x" in item and "unit" in item for item in report.weak)


def test_a_submission_without_provenance_is_weak_not_rejected():
    doc = example()
    del doc["provenance"]
    report = validate_submission(doc, design=design())
    assert report.ok, "the schema does not require provenance; the report says the data cannot be traced"
    assert report.evidence_level == "E0"
    assert report.e3_for == []
    assert any("provenance" in gap for gap in report.e3_gaps)


# --- the guide and the validator agree ----------------------------------------------------------


def test_the_guide_documents_the_units_the_validator_enforces():
    text = GUIDE.read_text(encoding="utf-8")
    for key, unit in UNIT_CONTRACT.items():
        assert f"`{key}`" in text, f"the guide does not mention the channel {key}"
        assert f"`{unit}`" in text, f"the guide does not state the unit {unit} of {key}"


def test_the_guide_lists_the_same_licence_choices():
    text = GUIDE.read_text(encoding="utf-8")
    for choice in LICENCE_CHOICES:
        assert choice in text, f"the guide does not mention the licence choice {choice}"


def test_the_guide_points_at_the_cli_and_the_example():
    text = GUIDE.read_text(encoding="utf-8")
    assert "scripts/validate_community_measurement.py" in text
    assert "schemas/examples/measurement-community-example.json" in text
    assert "docs/LICENSING.md" in text


def test_the_command_the_guide_asks_for_works_on_the_example():
    result = subprocess.run(
        [sys.executable, str(CLI), str(EXAMPLE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ACCEPTED" in result.stdout


def test_the_cli_rejects_a_broken_submission_with_a_non_zero_status(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(CLI), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "REJECTED" in result.stdout


def test_the_report_can_be_serialised():
    report = validate_submission(example(), design=design())
    assert isinstance(report, CommunityReport)
    assert json.loads(json.dumps(report.asdict()))["ok"] is True


def test_the_example_can_be_compared_with_a_simulation():
    """The channels the calibration machinery consumes must be present and consistent."""
    import numpy as np

    from strandbeest_calib import curves

    ch = example()["channels"]
    c = curves(np.array(ch["t"]), np.array(ch["psi"]), np.array(ch["torque"]), np.array(ch["x"]))
    assert c.stride == pytest.approx(0.114, rel=0.05)
    assert not np.isnan(c.torque).all()
