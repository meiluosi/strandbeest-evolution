"""A fit must replay the measured experiment, not the Design's default speed."""

import copy
import importlib

import numpy as np
import pytest

from strandbeest_calib.calibrate import CONTACT_STIFFNESS, apply_parameters, calibrate
from strandbeest_calib.conditions import measurement_scenario, scenario_conditions, validate_conditions
from strandbeest_common import Design
from strandbeest_common.ids import new_ulid
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.config import sim_config


@pytest.fixture(scope="module")
def experiment():
    design = Design.load(schema_dir() / "examples/design-jansen-small-6leg.json")
    design.doc["walker"]["legs"] = 2
    base = scenario_from_design(design, {"drive": {"omega": 4.0}, "terrain": {"kind": "slope", "slope_deg": 2.0},
                                         "run": {"frame_rate": 0}})
    result = run(apply_parameters(design, base, {"contact_stiffness": CONTACT_STIFFNESS.init}))
    measurement = {"schema_version": 2, "id": new_ulid(), "name": "nondefault-speed-synthetic", "design_id": design.id,
                   "synthetic": True, "conditions": scenario_conditions(base),
                   "channels": {"t": result.t.tolist(), "psi": result.psi.tolist(),
                                "torque": result.torque.tolist(), "x": result.x.tolist()}}
    return design, measurement


@pytest.mark.parametrize("method", ["nelder", "bayes"])
def test_both_calibrators_use_actual_conditions_and_keep_them_in_profile(experiment, method, monkeypatch):
    design, measurement = experiment
    module = importlib.import_module("strandbeest_calib.calibrate" if method == "nelder" else "strandbeest_calib.bayes_job")
    calls = []
    native = module.run

    def observed(scenario):
        cfg = sim_config(scenario)
        calls.append((cfg.drive.omega, cfg.terrain.kind, cfg.terrain.slope_deg, cfg.wind.speed))
        return native(scenario)

    monkeypatch.setattr(module, "run", observed)
    if method == "nelder":
        profile = calibrate(design, measurement, [CONTACT_STIFFNESS], max_evals=1)
        assert profile["provenance"]["residual"] < 1e-10
    else:
        profile = module.calibrate_bayes(design, measurement, ["contact_stiffness"], points=8)
    assert calls and all(row == (4.0, "slope", 2.0, 0.0) for row in calls)
    assert scenario_conditions(profile["scenario"]) == measurement["conditions"]
    assert design.doc["drive"]["motor_omega_rad_s"] == 2.0


@pytest.mark.parametrize("change,match", [
    ({"omega_rad_s": None}, "explicit finite"),
    ({"omega_rad_s": 0}, "positive crank"),
    ({"wind_m_s": 1}, "zero wind"),
    ({"kind": "fan", "wind_m_s": None}, "explicit finite"),
    ({"kind": "fan", "wind_m_s": 2}, "sail Design"),
    ({"slope_deg": 90}, "incline"),
])
def test_missing_or_unsupported_conditions_are_rejected(experiment, change, match):
    design, source = experiment
    measurement = copy.deepcopy(source)
    measurement["conditions"].update(change)
    # A missing field has schema validity, but cannot be guessed for a fit.
    measurement["conditions"] = {key: value for key, value in measurement["conditions"].items() if value is not None}
    with pytest.raises(ValueError, match=match):
        measurement_scenario(design, measurement)


def test_fan_speed_is_applied_and_varying_wind_is_not_averaged_away(experiment):
    design, source = experiment
    doc = copy.deepcopy(design.doc)
    doc["drive"]["kind"] = "sail"
    design = Design(doc)
    measurement = copy.deepcopy(source)
    measurement["conditions"] = {"kind": "fan", "wind_m_s": 2.5}
    cfg = sim_config(measurement_scenario(design, measurement))
    assert cfg.drive.kind == "sail" and cfg.wind.speed == 2.5
    measurement["channels"]["wind"] = np.linspace(2.0, 3.0, len(measurement["channels"]["t"])).tolist()
    with pytest.raises(ValueError, match="varying measured wind"):
        measurement_scenario(design, measurement)


def test_explicit_twin_scenario_rejects_conflicting_measurement_metadata(experiment):
    design, source = experiment
    with pytest.raises(ValueError, match="omega_rad_s"):
        validate_conditions(source, scenario_from_design(design))
    validate_conditions(source, measurement_scenario(design, source))
    with pytest.raises(ValueError, match="incline"):
        apply_parameters(design, measurement_scenario(design, source), {"sand_resistance": 2800})
