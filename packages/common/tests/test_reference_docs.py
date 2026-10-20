"""E1-05: reference docs and the assumptions inventory are generated from schema annotations and checked in CI."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "gen_reference_docs.py"
REF_DIR = ROOT / "docs" / "reference"


def test_committed_reference_docs_are_up_to_date():
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_fails_when_a_generated_file_is_stale(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0
    (tmp_path / "README.md").write_text("stale\n")
    chk = subprocess.run([sys.executable, str(SCRIPT), "--check", "--out", str(tmp_path)], capture_output=True, text=True)
    assert chk.returncode == 1 and "stale:" in chk.stdout


def test_assumptions_inventory_lists_every_assumed_parameter_with_its_source():
    readme = (REF_DIR / "README.md").read_text()
    for expected in (
        "walker.body_mass_kg",
        "drive.sail.area_m2",
        "manufacturing.clearance_mm",
        "entities[].components.body.foot_friction",
        "entities[].components.body.joint_friction",
        "entities[].components.drive.crank_friction",
        "solver.contact_stiffness",
    ):
        assert f"`{expected}`" in readme
