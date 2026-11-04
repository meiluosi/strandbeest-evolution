"""Required Python binding against independent pre-migration reference and shared corpora."""
import json
import math
import copy
import pickle
from dataclasses import replace
from pathlib import Path

import beest_kernel
import pytest
import reference_kinematics as reference
from strandbeest_common import gait_metrics, load_spec, solve_pose
from strandbeest_common.gait import foot_path
from strandbeest_common.linkage import _kernel_spec

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = sorted((ROOT / "contracts/kinematics").glob("*.json"))
BOUNDARIES = json.loads((ROOT / "contracts/kernel-boundaries.json").read_text())


@pytest.mark.parametrize("file", CONTRACTS, ids=lambda p: p.stem)
def test_all_contracts_against_independent_reference(file):
    doc = json.loads(file.read_text())
    spec = load_spec(doc["spec"])
    for i in range(180):
        theta = math.tau * i / 180
        actual, expected = solve_pose(spec, theta), reference.solve_pose(spec, theta)
        assert actual.keys() == expected.keys()
        for key in actual:
            assert actual[key] == pytest.approx(expected[key], abs=1e-9)
    actual_path = foot_path(spec)
    expected_path = reference.foot_path(spec)
    for a, b in zip(actual_path, expected_path, strict=True):
        assert a == pytest.approx(b, abs=1e-9)
    for tolerance in (0, 0.015, 0.1):
        actual = gait_metrics(spec, tol=tolerance)
        expected = reference.gait_metrics(spec, tol=tolerance)
        assert actual.asdict() == pytest.approx(expected.asdict(), abs=1e-9)


@pytest.mark.parametrize("case", BOUNDARIES["cases"], ids=lambda c: c["name"])
def test_shared_invalid_and_degenerate_inputs(case):
    spec = load_spec(case["spec"])
    samples = case.get("samples", BOUNDARIES["samples"])
    if case["outcome"] == "error":
        with pytest.raises(ValueError):
            foot_path(spec, samples)
        with pytest.raises(ValueError):
            gait_metrics(spec, samples)
        return
    path = foot_path(spec, samples)
    assert (path is not None) == (case["outcome"] == "assembled")
    expected_path = reference.foot_path(spec, samples)
    assert (path is not None) == (expected_path is not None)
    if path is None:
        trajectory = beest_kernel.trace_trajectory(_kernel_spec(spec), samples)
        assert trajectory.points == [] and trajectory.poses == []
        assert gait_metrics(spec, samples).asdict() == dict(width=0, lift=0, stroke_length=0, duty=0, assembled=False)
    else:
        for a, b in zip(path, expected_path, strict=True):
            assert a == pytest.approx(b, abs=1e-9)


def test_adapter_uses_required_native_functions_and_propagates_failure(monkeypatch):
    def unavailable(*args):
        raise RuntimeError("native kernel failure")
    monkeypatch.setattr(beest_kernel, "Linkage", unavailable)
    for invoke in (lambda s: solve_pose(s, 0), foot_path, gait_metrics):
        spec = load_spec(BOUNDARIES["cases"][0]["spec"])
        with pytest.raises(RuntimeError, match="native kernel failure"):
            invoke(spec)


def test_bad_sampling_nonfinite_parameters_and_mutable_parameter_updates():
    doc = json.loads(CONTRACTS[0].read_text())
    spec = load_spec(doc["spec"])
    for samples in (0, -1, 1_000_001):
        with pytest.raises((ValueError, OverflowError)):
            foot_path(spec, samples)
    with pytest.raises(ValueError):
        solve_pose(spec, math.nan)
    with pytest.raises(ValueError):
        gait_metrics(spec, tol=-1)
    before = solve_pose(spec, 0)
    spec.params["m"] *= 1.1
    assert solve_pose(spec, 0) != before  # no stale compiled-spec cache
    spec.params["m"] = math.inf
    with pytest.raises(ValueError):
        solve_pose(spec, 0)


def test_cached_spec_branch_replacement_copy_and_pickle_are_independent():
    from strandbeest_common.linkage import _kernel
    spec = load_spec(BOUNDARIES["cases"][0]["spec"])
    pose = solve_pose(spec, 0)
    first_native = _kernel(spec)
    assert isinstance(first_native, beest_kernel.Linkage)
    assert _kernel(spec) is first_native
    branch = replace(spec, joints=(replace(spec.joints[0], side=-1),))
    assert solve_pose(branch, 0)["F"][1] == pytest.approx(-pose["F"][1])
    assert _kernel(branch) is not first_native
    for copied in (copy.deepcopy(spec), pickle.loads(pickle.dumps(spec))):
        assert solve_pose(copied, 0) == pose
        assert _kernel(copied) is not first_native
        copied.params["unused"] = 12
        assert "unused" not in spec.params
