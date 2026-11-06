"""Q-01: Golden run benchmarks and mutation sensitivity tests.

Acceptance criteria:
  - Golden benchmark suite: fixed design + scenarios reference results with numerical tolerances.
  - Deliberately perturbing a physical parameter (e.g. gravity x 1.1, contact stiffness x 1.2 or 0.8,
    joint friction) raises regression failure and flags the anomaly with explicit error output.
  - Supports verification via CI and CLI runner script.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
from strandbeest_sim import load_scenario, run

# Ensure sim scripts are on sys.path so we can reuse run_golden_benchmarks logic
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_golden_benchmarks import (  # noqa: E402
    DEFAULT_RTOL,
    apply_mutation,
    compare_run_against_golden,
    load_golden_catalog,
    run_benchmark,
)

GOLDEN_RUNS, OBSERVATIONS = load_golden_catalog()
GOLDEN_MAP = {r["name"]: r for r in GOLDEN_RUNS}


def assert_golden_regression(
    res: Any,
    golden_entry: dict[str, Any],
    obs_entry: dict[str, Any],
    rtol: float = DEFAULT_RTOL,
) -> None:
    """Assert that a simulation result matches golden records, raising AssertionError on diffs."""
    diffs = compare_run_against_golden(res, golden_entry, obs_entry, rtol=rtol)
    if diffs:
        err_msg = (
            f"Golden regression anomaly detected for scenario '{golden_entry['name']}' "
            f"({len(diffs)} mismatches):\n" + "\n".join(f"  - {d}" for d in diffs[:8])
        )
        raise AssertionError(err_msg)


def test_golden_unperturbed_baseline_passes():
    """Verify that an unperturbed golden run reproduces the reference baseline."""
    g = GOLDEN_MAP["flat-motor"]
    obs = OBSERVATIONS["flat-motor"]

    sc = load_scenario(g["scenario"])
    res = run(sc)

    # Must pass without any differences
    diffs = compare_run_against_golden(res, g, obs)
    assert not diffs, f"Unperturbed run had unexpected diffs: {diffs}"
    assert_golden_regression(res, g, obs)


def test_perturb_gravity_flags_anomaly():
    """Mutating gravity (e.g. g * 1.1) must trigger regression failure with explicit anomaly output."""
    g = GOLDEN_MAP["flat-motor"]
    obs = OBSERVATIONS["flat-motor"]

    mutated_doc, desc = apply_mutation(g["scenario"], "gravity:1.1")
    assert "environment.gravity" in desc

    res = run(load_scenario(mutated_doc))
    diffs = compare_run_against_golden(res, g, obs)

    # Verify differences exist and explicitly identify the anomaly
    assert len(diffs) > 0, "Gravity perturbation was not detected!"
    diff_text = "\n".join(diffs)
    assert "mismatch" in diff_text

    # Expect assertion error with clear diagnostic
    with pytest.raises(AssertionError) as exc_info:
        assert_golden_regression(res, g, obs)
    assert "Golden regression anomaly detected" in str(exc_info.value)
    assert "flat-motor" in str(exc_info.value)


@pytest.mark.parametrize("factor", [1.2, 0.8], ids=["stiffness-up-1.2", "stiffness-down-0.8"])
def test_perturb_contact_stiffness_flags_anomaly(factor: float):
    """Mutating contact stiffness (k * 1.2 or k * 0.8) must trigger regression failure."""
    g = GOLDEN_MAP["flat-motor"]
    obs = OBSERVATIONS["flat-motor"]

    mutated_doc, desc = apply_mutation(g["scenario"], f"stiffness:{factor}")
    assert "solver.contact_stiffness" in desc

    res = run(load_scenario(mutated_doc))
    diffs = compare_run_against_golden(res, g, obs)

    assert len(diffs) > 0, f"Stiffness perturbation (factor {factor}) was not detected!"
    with pytest.raises(AssertionError) as exc_info:
        assert_golden_regression(res, g, obs)
    assert "Golden regression anomaly detected" in str(exc_info.value)


def test_perturb_joint_friction_flags_anomaly():
    """Mutating joint friction (e.g. setting to 0.05) must trigger regression failure."""
    g = GOLDEN_MAP["flat-motor"]
    obs = OBSERVATIONS["flat-motor"]

    mutated_doc, desc = apply_mutation(g["scenario"], "joint_friction:0.05")
    assert "walker.joint_friction" in desc

    res = run(load_scenario(mutated_doc))
    diffs = compare_run_against_golden(res, g, obs)

    assert len(diffs) > 0, "Joint friction perturbation was not detected!"
    # Verify specific metrics diverged
    assert any("energy" in d or "torque" in d or "sample" in d for d in diffs)

    with pytest.raises(AssertionError) as exc_info:
        assert_golden_regression(res, g, obs)
    assert "Golden regression anomaly detected" in str(exc_info.value)


def test_cli_golden_benchmark_detects_mutation():
    """Verify that run_benchmark CLI logic returns 0 when --expect-failure flags mutations."""
    exit_code, report = run_benchmark(
        scenario_filter="flat-motor",
        mutation_spec="gravity:1.1",
        expect_failure=True,
        verbose=False,
    )
    assert exit_code == 0
    assert report["overall_success"] is True
    assert report["runs"][0]["status"] == "MUTATION_DETECTED"
    assert report["runs"][0]["diff_count"] > 0


def test_cli_golden_benchmark_flags_regression_failure():
    """Verify that run_benchmark flags exit code 1 when an unexpected regression occurs."""
    exit_code, report = run_benchmark(
        scenario_filter="flat-motor",
        mutation_spec="gravity:1.1",
        expect_failure=False,
        verbose=False,
    )
    assert exit_code == 1
    assert report["overall_success"] is False
    assert report["runs"][0]["status"] == "REGRESSION_FAILED"


@pytest.mark.slow
@pytest.mark.parametrize("scenario_name", ["slope-5deg", "mars-gravity"])
def test_slow_multi_scenario_mutation_sensitivity(scenario_name: str):
    """Slow suite: verify multiple diverse golden scenarios flag deliberate perturbations."""
    g = GOLDEN_MAP[scenario_name]
    obs = OBSERVATIONS[scenario_name]

    mutated_doc, _ = apply_mutation(g["scenario"], "gravity:1.1")
    res = run(load_scenario(mutated_doc))
    diffs = compare_run_against_golden(res, g, obs)

    assert len(diffs) > 0, f"Scenario {scenario_name} failed to detect gravity mutation!"
    with pytest.raises(AssertionError):
        assert_golden_regression(res, g, obs)
