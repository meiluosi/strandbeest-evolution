"""W-01: every drive declares where its energy comes from, and runs report whether the result is wind-only (docs/WIND.md section 2)."""

import pytest

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.registry import ENERGY_SOURCES, Registry, drives

DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
SHORT = {"run": {"revolutions": 0.3, "settle": 0.2, "give_up_after": 3, "max_time": 6, "frame_rate": 0}}


def test_builtin_drives_declare_their_energy_source():
    assert drives.meta("sail")["energy_source"] == "wind"
    assert drives.meta("motor")["energy_source"] == "test_rig"
    assert all(drives.meta(n)["energy_source"] in ENERGY_SOURCES for n in drives.names())


def test_a_drive_without_an_energy_source_cannot_be_registered():
    with pytest.raises(ValueError, match="energy_source"):
        drives.register("freeloader")(lambda sim: None)
    assert "freeloader" not in drives.names()


def test_an_unknown_energy_source_is_rejected():
    reg = Registry("drive", required_meta=("energy_source",), choices={"energy_source": ENERGY_SOURCES})
    with pytest.raises(ValueError, match="not one of"):
        reg.register("flux", energy_source="perpetual_motion")(lambda sim: None)


def test_unknown_drive_name_still_gives_the_helpful_error():
    with pytest.raises(KeyError, match="available"):
        drives.meta("nope")


def test_runs_report_wind_only():
    sail = run(scenario_from_design(DESIGN, {**SHORT, "drive": {"kind": "sail"}, "wind": {"speed": 3.0}}))
    motor = run(scenario_from_design(DESIGN, SHORT))
    assert sail.metrics["wind_only"] is True
    assert motor.metrics["wind_only"] is False
