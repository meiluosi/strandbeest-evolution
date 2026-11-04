from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from strandbeest_calib.bayes import (
    CalibrationProfile, DigitalTwinModel, calibrate_digital_twin_bayes,
    log_likelihood_digital_twin, simulate_digital_twin_trajectories,
)
from strandbeest_calib.calibrate import BAR_FLEXIBILITY, PARAMETERS, parameter_overrides, parameter_registry
from strandbeest_calib.forward import document_hash
from strandbeest_common import Design
from strandbeest_common.ids import new_ulid
from strandbeest_common.schemas import schema_dir, validate
from strandbeest_common.scenario import flatten, to_v2
from strandbeest_sim import run, scenario_from_design

TIMES = np.linspace(0.0, 0.15, 16)
TRUTH = {"pin_friction": 0.0015}
PRIORS = {"pin_friction": (0.0004, 0.004)}


def make_model(fixture=None):
    doc = json.loads((schema_dir()/"examples/design-jansen-small-6leg.json").read_text())
    doc["walker"]["legs"] = 2
    if fixture:
        doc["linkage"] = json.loads((schema_dir().parent/"contracts/kinematics"/f"{fixture}.json").read_text())["spec"]
    design = Design(doc)
    scenario = scenario_from_design(design, {"run": {"settle": 0.05, "max_time": 0.3, "revolutions": 2},
                                           "drive": {"omega": 4, "ramp": 0.03, "max_torque": 0.3}})
    return DigitalTwinModel(design, scenario)


def fit(model, measurement, **kwargs):
    return calibrate_digital_twin_bayes(model, measurement, PRIORS, n_samples=300, burn_in=100,
                                       seed=123, emulator_points=8, validation_points=3, **kwargs)


@pytest.mark.parametrize("fixture", [None, "fourbar-crank-rocker", "sixbar-extra-dyad"])
def test_native_forward_matches_actual_frames_for_explicit_design(fixture):
    model = make_model(fixture)
    prediction = model.predict(TRUTH, TIMES)
    native = run(model.last_native_scenario, backend="mujoco")
    frames = native.frames
    torso = frames["pos"][:, native.scene["bodies"].index("torso"), :]
    relative = frames["foot_pos"][:, 0, :]-torso
    expected = np.column_stack([np.interp(TIMES, frames["t"], relative[:, k]) for k in (0, 2)])
    assert prediction.foot_path == pytest.approx(expected, abs=1e-8)
    assert prediction.crank_angle == pytest.approx(np.interp(TIMES, native.t, native.psi))
    assert prediction.x_hip == pytest.approx(np.interp(TIMES, native.t, native.x)-native.x[0])
    assert prediction.omega == pytest.approx(np.interp(TIMES, native.t, np.gradient(native.psi, native.t, edge_order=2)))
    assert model.last_native_scenario["entities"][0]["components"]["linkage"]["spec"] == model.design.doc["linkage"]
    record = model.native_runs[-1]
    assert record["completed"] and record["implementation_unchanged"]
    assert record["parameters"] == TRUTH
    assert record["scenario"] == model.last_native_scenario
    assert record["scenario_sha256"] == document_hash(record["scenario"])
    assert record["scenario_sha256"] != model.provenance["scenario_sha256"]  # actual recording/stop budget is explicit


@pytest.mark.parametrize("name,low,high,path", [
    ("pin_friction", .0004, .004, ("walker", "joint_friction")),
    ("contact_stiffness", 1e4, 2e5, ("solver", "contact_stiffness")),
    ("friction", .3, 2., ("terrain", "friction")),
    ("sand_resistance", 1000., 5000., ("terrain", "params", "stiffness")),
])
def test_registered_parameter_changes_native_model_and_roundtrips(name, low, high, path):
    model = make_model()
    a = model.predict({name: low}, TIMES)
    b = model.predict({name: high}, TIMES)
    assert np.max(np.abs(a.omega-b.omega)) > 1e-5
    doc = model.scenario_for({name: high}).model_dump(mode="json", exclude_unset=True)
    flat = flatten(doc)
    value = flat
    for key in path:
        value = value[key]
    assert value == high
    assert flatten(to_v2(flat)) == flat
    assert model.scenario.world.terrain.kind == "flat"  # mapping does not mutate the baseline
    if name == "sand_resistance":
        assert "damping" not in flat["terrain"]["params"]  # independent damping remains unchanged


@pytest.mark.parametrize("values", [{"bar_flexibility": .002}, {"k_flex": .002}, {"mu_pin": .001},
                                     {"alpha_sand": 2800}, {"unknown": 1}, {"pin_friction": True},
                                     {"pin_friction": float("nan")}, {"pin_friction": .02},
                                     {"contact_stiffness": 1e5, "sand_resistance": 2800}])
def test_unsupported_or_ambiguous_parameters_fail_before_native_call(values):
    model = make_model()
    with pytest.raises(ValueError):
        model.predict(values, TIMES)
    assert model.native_calls == 0
    assert BAR_FLEXIBILITY.supported is False


def test_contact_mapping_rejects_inactive_soft_terrain():
    model = make_model()
    model.scenario.world.terrain.kind = "sand"
    with pytest.raises(ValueError, match="overridden"):
        model.predict({"contact_stiffness": 1e5}, TIMES)
    assert model.native_calls == 0


def test_design_relative_leg_mass_changes_the_actual_forward_model():
    model = make_model()
    p = parameter_registry(model.design)["leg_mass_per_m"]
    light = model.predict({p.name: p.lo}, TIMES)
    heavy = model.predict({p.name: p.hi}, TIMES)
    assert np.max(np.abs(light.omega-heavy.omega)) > 1e-5
    assert flatten(model.last_native_scenario)["walker"]["tube_mass_per_m"] == p.hi


@pytest.mark.parametrize("times", [[0, .1, .1], [-.01, 0, .01], [0, .000001, .1], [0, .1, .4]])
def test_sampling_contract_rejects_aliasing_and_extrapolation(times):
    model = make_model()
    with pytest.raises(ValueError):
        model.predict(TRUTH, np.array(times))
    assert model.native_calls == 0


def test_forward_requires_actual_design_and_matching_scenario():
    with pytest.raises(TypeError):
        DigitalTwinModel()
    model = make_model()
    with pytest.raises(ValueError, match="backend"):
        DigitalTwinModel(model.design, backend="toy")
    mismatch = copy.deepcopy(model.scenario)
    mismatch.entities[0].components.body.unit *= 2
    with pytest.raises(ValueError, match="scale"):
        DigitalTwinModel(model.design, mismatch)


def test_synthetic_recovery_native_holdout_and_executable_profile(tmp_path):
    model = make_model()
    obs = simulate_digital_twin_trajectories(model, TRUTH, TIMES, noise_sigma=1e-5, seed=42)
    report = fit(model, obs.measurement)
    assert report.map_estimate["pin_friction"] == pytest.approx(TRUTH["pin_friction"], rel=.1)
    assert report.profile.uncertainty["pin_friction"]["identifiable"] is True
    assert report.validation["native_calls"] == 8+3+1+2
    assert len(report.validation["native_runs"]) == report.validation["native_calls"]
    assert all(row["completed"] and row["implementation_unchanged"] for row in report.validation["native_runs"])
    assert report.validation["emulator_holdout_normalized_rmse"] < 1
    assert report.validation["native_time_holdout_normalized_rmse"] < 2
    assert max(report.validation["fit_time_indices"]) < min(report.validation["held_out_time_indices"])
    profile = report.profile.to_dict()
    applied = model.apply_profile(profile)
    restored = DigitalTwinModel(model.design, applied).predict({}, TIMES)
    predicted = model.predict(profile["parameters"], TIMES)
    assert restored.foot_path == pytest.approx(predicted.foot_path)
    assert profile["parameters"] == report.map_estimate
    report.save_json(tmp_path/"report.json")
    saved = json.loads((tmp_path/"report.json").read_text())
    assert saved["measurement"] == obs.measurement
    assert saved["validation"]["forward_model"]["design_id"] == model.design.id
    assert saved["profile"]["provenance"]["measurement_ids"] == [obs.measurement["id"]]
    assert "pin_friction" in report.summary()
    profile["provenance"]["design_id"] = new_ulid()
    with pytest.raises(ValueError, match="design_id"):
        model.apply_profile(profile)


def test_realistic_video_noise_reports_unidentifiable_short_window():
    model = make_model()
    obs = simulate_digital_twin_trajectories(model, TRUTH, TIMES, noise_sigma=.0008, seed=42)
    report = fit(model, obs.measurement)
    uncertainty = report.profile.uncertainty["pin_friction"]
    assert uncertainty["identifiable"] is False
    assert uncertainty["profile_share_of_prior"] > .9


def test_joint_fit_rejects_false_certainty_from_inaccurate_emulator(monkeypatch):
    from strandbeest_calib import physical_inference

    model = make_model()
    truth = {"pin_friction": .0015, "contact_stiffness": 2e5}
    obs = simulate_digital_twin_trajectories(model, truth, TIMES, noise_sigma=1e-5, seed=42)
    priors = {"pin_friction": (.0004, .004), "contact_stiffness": (4e4, 8e5)}
    settings = dict(n_samples=300, burn_in=100, seed=123, emulator_points=24, validation_points=4, profile_grid=15)
    baseline = calibrate_digital_twin_bayes(model, obs.measurement, priors, **settings)
    assert baseline.validation["emulator_holdout_normalized_rmse"] < 3
    assert all(u["identifiable"] for u in baseline.profile.uncertainty.values())

    interpolator = physical_inference.RBFInterpolator

    def batch_error(*args, **kwargs):
        estimate = interpolator(*args, **kwargs)

        def predict(points):
            result = estimate(points)
            # A controlled 1-mm batch-evaluation fault in the foot-x channel.
            # Native observations and single-query fitting remain untouched;
            # the independently evaluated holdout must veto false certainty.
            if len(points) > 1:
                result = result.copy()
                result[:, :len(TIMES)] += .001
            return result

        return predict

    monkeypatch.setattr(physical_inference, "RBFInterpolator", batch_error)
    report = calibrate_digital_twin_bayes(model, obs.measurement, priors, **settings)
    assert report.map_estimate == baseline.map_estimate
    assert report.credible_intervals_95 == baseline.credible_intervals_95
    assert report.validation["emulator_holdout_normalized_rmse"] > 3
    assert not any(u["identifiable"] for u in report.profile.uncertainty.values())
    assert len(report.validation["native_sensitivity_directions"]) == 2


def synthetic_source(model):
    return simulate_digital_twin_trajectories(model, TRUTH, TIMES, noise_sigma=1e-5, seed=7).measurement


def physical_metadata_fixture(model):
    """Exercise the physical metadata path with test arrays; this is NOT E3 evidence."""
    doc = synthetic_source(model)
    doc["synthetic"] = False
    doc["provenance"].update(source="rig", raw_file="fixture-only.mp4")
    doc["provenance"]["calibration"].update(
        instrument="test camera metadata only", measured_on="2026-11-01", calibrated_on="2026-10-31",
        camera={"camera_matrix": [[600, 0, 320], [0, 600, 240], [0, 0, 1]],
                "dist_coeffs": [0, 0, 0, 0, 0], "image_size": [640, 480]},
    )
    return doc


def test_declared_physical_measurement_keeps_identity_and_is_not_silently_marked_synthetic():
    model = make_model()
    doc = physical_metadata_fixture(model)
    report = fit(model, doc)
    assert report.profile.provenance["synthetic"] is False
    assert report.profile.provenance["measurement_ids"] == [doc["id"]]
    assert report.measurement == doc
    doc["provenance"]["raw_file"] = "changed-after-calibration.mp4"
    assert report.measurement["provenance"]["raw_file"] == "fixture-only.mp4"


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda d: d.pop("id"), "id"),
        (lambda d: d.pop("synthetic"), "synthetic"),
        (lambda d: d["provenance"].pop("raw_file"), "raw_file"),
        (lambda d: d["provenance"]["calibration"].pop("measured_on"), "measured_on"),
        (lambda d: d["provenance"]["calibration"].pop("camera"), "camera"),
        (lambda d: d["provenance"]["calibration"]["camera"].update(camera_matrix=[]), "camera calibration"),
        (lambda d: d["provenance"]["calibration"]["units"].update(foot_x="mm"), "unit m"),
        (lambda d: d["provenance"]["calibration"]["uncertainty"].pop("omega"), "uncertainty"),
        (lambda d: d["provenance"]["calibration"].pop("uncertainty_kind"), "absolute_1sigma"),
        (lambda d: d["channels"]["foot_x"].pop(), "equal-length"),
        (lambda d: d["channels"]["t"].reverse(), "strictly increasing"),
        (lambda d: d["provenance"]["calibration"].pop("alignment"), "alignment"),
        (lambda d: d.update(design_id=new_ulid()), "design_id"),
    ],
)
def test_calibration_rejects_untraceable_or_inconsistent_input_before_inference(mutation, match):
    model = make_model()
    doc = physical_metadata_fixture(model)
    mutation(doc)
    with pytest.raises(ValueError, match=match):
        calibrate_digital_twin_bayes(model, doc, n_samples=10, burn_in=0)


def test_unidentified_raw_observations_do_not_get_a_fabricated_measurement_id():
    model = make_model()
    with pytest.raises(ValueError, match="Measurement document"):
        calibrate_digital_twin_bayes(model, {"t": [0, 1], "foot_path": [[0, 0], [1, 1]], "omega": [1, 1]})


def test_measurement_errors_are_used_in_likelihood():
    from strandbeest_calib.bayes import _digital_twin_measurement

    model = make_model()
    doc = synthetic_source(model)
    _, observations, small_sigmas = _digital_twin_measurement(doc)
    looser = copy.deepcopy(doc)
    looser["provenance"]["calibration"]["uncertainty"] = {
        key: value * 2 for key, value in doc["provenance"]["calibration"]["uncertainty"].items()
    }
    _, _, large_sigmas = _digital_twin_measurement(looser)
    params = TRUTH
    assert log_likelihood_digital_twin(model, observations, params, large_sigmas) == pytest.approx(
        log_likelihood_digital_twin(model, observations, params, small_sigmas) / 4
    )


def test_tracked_measurement_round_trip_through_calibration_keeps_resolvable_source(tmp_path):
    from strandbeest_rig.video_track import MultiKeypointTrackResult

    model = make_model()
    source = synthetic_source(model)
    ch = source["channels"]
    t = np.asarray(ch["t"])
    hip = np.column_stack([ch["x"], np.zeros(len(t))])
    foot = np.column_stack([ch["foot_x"], ch["foot_y"]])
    tracked = MultiKeypointTrackResult(
        t=t, trajectories={"hip": hip, "foot": hip + foot, "crank": hip + 0.01},
        omega=np.asarray(ch["omega"]), foot_path=foot, crank_angle=np.asarray(ch["psi"]),
        fps=(len(t) - 1) / (t[-1] - t[0]), frames=len(t),
        detected_fractions={"hip": 1.0, "foot": 1.0, "crank": 1.0}, metres_per_pixel=0.001,
        synthetic=True,
    )
    provenance = copy.deepcopy(source["provenance"])
    provenance["calibration"]["uncertainty"].update(t=0.001, psi=0.02)
    measurement = tracked.to_measurement(
        measurement_id=source["id"], design_id=source["design_id"], name="synthetic-tracking-round-trip",
        conditions=source["conditions"], provenance=provenance, crank_direction=1,
    )
    source_path = tmp_path / f"{measurement['id']}.json"
    source_path.write_text(json.dumps(measurement))
    report = fit(model, json.loads(source_path.read_text()))
    profile = report.profile.to_dict()
    assert profile["provenance"]["measurement_ids"] == [source_path.stem]
    assert profile["provenance"]["synthetic"] is True
    assert report.measurement == json.loads(source_path.read_text())


def test_implementation_drift_between_native_runs_is_rejected(monkeypatch):
    from strandbeest_calib.identity import CALIBRATION_IMPLEMENTATION

    model = make_model()
    source = synthetic_source(model)
    native = model.predict
    first = model.native_calls + 1

    def changed_after_run(parameters, times):
        prediction = native(parameters, times)
        if model.native_calls == first:
            # No individual run crosses the change: the guard must also compare runs.
            monkeypatch.setattr(CALIBRATION_IMPLEMENTATION, "current", lambda: {
                "status": "unavailable", "reason": "test: source changed between native calls"})
        return prediction

    monkeypatch.setattr(model, "predict", changed_after_run)
    with pytest.raises(ValueError, match="implementation changed"):
        fit(model, source)
