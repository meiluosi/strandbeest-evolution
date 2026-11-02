"""Parity tests comparing Rust beest_kernel against strandbeest_common Python implementation."""

import json
import math
from pathlib import Path
import pytest

import beest_kernel
from strandbeest_common.gait import foot_path as py_foot_path, gait_metrics as py_gait_metrics
from strandbeest_common.linkage import load_spec, solve_pose as py_solve_pose


@pytest.fixture
def jansen_contract():
    contract_path = Path(__file__).resolve().parents[3] / "contracts" / "kinematics" / "jansen.json"
    return json.loads(contract_path.read_text())


def test_jansen_eleven_numbers_pose_parity(jansen_contract):
    spec_dict = jansen_contract["spec"]
    spec_json = json.dumps(spec_dict)
    py_spec = load_spec(spec_dict)

    # Verify eleven numbers explicitly
    expected_params = {
        "a": 38,
        "b": 41.5,
        "c": 39.3,
        "d": 40.1,
        "e": 55.8,
        "f": 39.4,
        "g": 36.7,
        "h": 65.7,
        "i": 49,
        "j": 50,
        "k": 61.9,
        "l": 7.8,
        "m": 15,
    }
    for k, v in expected_params.items():
        assert py_spec.params[k] == v

    # Sweep crank angles and compare every joint position
    num_angles = 72
    for i in range(num_angles):
        theta = 2.0 * math.pi * i / num_angles
        py_pose = py_solve_pose(py_spec, theta)
        assert py_pose is not None

        rust_pose = beest_kernel.solve_pose(spec_json, theta)
        assert rust_pose is not None

        # Verify exact same joint keys
        assert set(rust_pose.keys()) == set(py_pose.keys())

        # Verify every coordinate matches within 1e-9 tolerance
        for joint_id, py_pt in py_pose.items():
            rust_pt = rust_pose[joint_id]
            assert rust_pt[0] == pytest.approx(py_pt[0], abs=1e-9), f"Joint {joint_id} x mismatch at theta={theta}"
            assert rust_pt[1] == pytest.approx(py_pt[1], abs=1e-9), f"Joint {joint_id} y mismatch at theta={theta}"


def test_jansen_trajectory_parity(jansen_contract):
    spec_dict = jansen_contract["spec"]
    spec_json = json.dumps(spec_dict)
    py_spec = load_spec(spec_dict)

    samples = 180
    py_path = py_foot_path(py_spec, samples=samples)
    assert py_path is not None

    rust_traj = beest_kernel.trace_trajectory(spec_json, samples=samples)
    assert rust_traj.assembled
    assert len(rust_traj) == samples
    assert len(rust_traj.points) == samples

    for i in range(samples):
        theta = 2.0 * math.pi * i / samples
        py_pt = py_path[i]
        rust_pt = rust_traj[i]
        assert rust_pt[0] == pytest.approx(py_pt[0], abs=1e-9), f"Foot x mismatch at index {i} (theta={theta})"
        assert rust_pt[1] == pytest.approx(py_pt[1], abs=1e-9), f"Foot y mismatch at index {i} (theta={theta})"
        assert rust_traj.points[i][0] == pytest.approx(py_pt[0], abs=1e-9)
        assert rust_traj.points[i][1] == pytest.approx(py_pt[1], abs=1e-9)


def test_jansen_gait_and_envelope_parity(jansen_contract):
    spec_dict = jansen_contract["spec"]
    spec_json = json.dumps(spec_dict)
    py_spec = load_spec(spec_dict)

    samples = 180
    py_gait = py_gait_metrics(py_spec, samples=samples)
    rust_gait = beest_kernel.compute_gait(spec_json, samples=samples)

    assert rust_gait.assembled
    assert rust_gait.width == pytest.approx(py_gait.width, abs=1e-9)
    assert rust_gait.lift == pytest.approx(py_gait.lift, abs=1e-9)
    assert rust_gait.stroke_length == pytest.approx(py_gait.stroke_length, abs=1e-9)
    assert rust_gait.duty == pytest.approx(py_gait.duty, abs=1e-9)
    assert rust_gait.duty_factor == pytest.approx(py_gait.duty, abs=1e-9)
    assert rust_gait.step_height == pytest.approx(py_gait.lift, abs=1e-9)

    # Test assemblability
    assert beest_kernel.check_assemblability(spec_json, samples=samples) is True

    # Test dyad envelope
    d_min, d_max = beest_kernel.compute_dyad_envelope(41.5, 50.0)
    assert d_min == pytest.approx(8.5, abs=1e-9)
    assert d_max == pytest.approx(91.5, abs=1e-9)
