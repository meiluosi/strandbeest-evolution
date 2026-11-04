"""An audit cannot turn absent/non-finite evidence or a zero value into a pass."""
import copy
import json
from dataclasses import asdict

import numpy as np
import pytest
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design
from strandbeest_sim.builder import resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.events import nominal_stride_m
from strandbeest_sim.skeptic import audit_legacy as audit, check_window_invariance


@pytest.fixture
def scenario():
    design = Design(json.loads((schema_dir() / "examples/design-jansen-small-6leg.json").read_text()))
    return sim_config(scenario_from_design(design))


def healthy_metrics(sc):
    return {"steady_window": 1.0, "energy_residual_share": 0.0,
            "max_loop_violation": 0.0, "max_penetration": 0.0,
            "stride_per_rev": nominal_stride_m(sc)}


@pytest.mark.parametrize("key", ["steady_window", "energy_residual_share", "max_loop_violation", "max_penetration", "stride_per_rev"])
@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf")])
def test_missing_and_nonfinite_metrics_are_explicit_findings_with_serializable_evidence(scenario, key, value):
    metrics = healthy_metrics(scenario)
    if value is None:
        del metrics[key]
    else:
        metrics[key] = value
    findings = audit(scenario, metrics)
    assert any(f.check == "audit_evidence" and f.evidence.get("metric") == key for f in findings)
    json.dumps([asdict(f) for f in findings], allow_nan=False)


@pytest.mark.parametrize("value", [[], [1, 2], [[1]], [[float("nan")]*6], [[float("inf")]*6], [[-1]*6]])
def test_supplied_support_samples_must_have_finite_nonnegative_loads_for_every_leg(scenario, value):
    findings = audit(scenario, healthy_metrics(scenario), {"foot_normal": np.asarray(value)})
    assert any(f.check == "audit_evidence" and f.evidence.get("metric") == "foot_normal" for f in findings)
    json.dumps([asdict(f) for f in findings], allow_nan=False)


def test_series_omission_is_explicitly_optional_but_a_supplied_series_must_include_support(scenario):
    assert audit(scenario, healthy_metrics(scenario)) == []
    assert any(f.check == "audit_evidence" for f in audit(scenario, healthy_metrics(scenario), {}))
    assert audit(scenario, healthy_metrics(scenario), {"foot_normal": np.ones((10, 6))}) == []


@pytest.mark.parametrize("key", ["max_loop_violation", "max_penetration"])
def test_negative_maximum_distances_are_invalid_evidence(scenario, key):
    metrics = healthy_metrics(scenario)
    metrics[key] = -0.001
    assert any(f.check == "audit_evidence" for f in audit(scenario, metrics))


@pytest.mark.parametrize("before,after", [(0., 1.), (1., 0.), (-1., 1.), (-1e308, 1e308)])
def test_window_comparison_does_not_skip_zero_or_a_change_of_direction(before, after):
    findings = check_window_invariance(lambda length: dict.fromkeys(
        ["stride_per_rev", "mean_torque", "mean_speed"], before if length == 3.0 else after))
    assert len(findings) == 3
    assert all(f.check == "window_invariance" for f in findings)
    assert all(f.evidence["relative"] >= 1 for f in findings)
    json.dumps([asdict(f) for f in findings], allow_nan=False)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf")])
def test_window_comparison_does_not_accept_unavailable_or_nonfinite_metrics(value):
    findings = check_window_invariance(lambda _: dict.fromkeys(["stride_per_rev", "mean_torque", "mean_speed"], value))
    assert len(findings) == 3
    json.dumps([asdict(f) for f in findings], allow_nan=False)


def test_equal_zero_and_negative_window_metrics_are_valid():
    for value in [0., -1.]:
        assert check_window_invariance(lambda _: dict.fromkeys(["stride_per_rev", "mean_torque", "mean_speed"], value)) == []


def test_nominal_and_audit_resolve_inline_overrides_and_named_specs_like_the_builder(scenario):
    original = nominal_stride_m(scenario)
    scenario.linkage.params = {"a": scenario.linkage.spec["params"]["a"] * 1.01}
    inline = scenario.model_copy(deep=True)
    inline.linkage.spec["params"].update(inline.linkage.params)
    inline.linkage.params = {}
    expected = nominal_stride_m(inline)
    assert expected != original
    assert nominal_stride_m(scenario) == expected
    assert resolve_spec(scenario) == resolve_spec(inline)
    named = scenario.model_copy(deep=True)
    named.linkage.spec = "jansen"
    # The small design uses the unmodified canonical parameter set except for
    # the explicit override; resolve_spec proves these are the same geometry.
    assert resolve_spec(named) == resolve_spec(scenario)
    assert nominal_stride_m(named) == expected
    metrics = healthy_metrics(named)
    metrics["stride_per_rev"] = 0.
    assert any(f.check == "stride_vs_kinematics" for f in audit(named, metrics))


def test_audit_does_not_modify_inputs(scenario):
    metrics = healthy_metrics(scenario)
    series = {"foot_normal": np.ones((10, 6))}
    before = copy.deepcopy((scenario, metrics, series))
    audit(scenario, metrics, series)
    assert scenario == before[0] and metrics == before[1]
    np.testing.assert_array_equal(series["foot_normal"], before[2]["foot_normal"])
