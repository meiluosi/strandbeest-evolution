#!/usr/bin/env python3
"""Run golden simulator benchmarks and mutation sensitivity tests (Q-01).

Acceptance Criteria:
  - Golden benchmark suite with numerical regression tolerances.
  - Verifies that deliberate physics parameter mutations (e.g. gravity x 1.1,
    contact stiffness x 1.2 or 0.8, joint friction) trigger regression failures
    and flag anomalies with explicit error messages.
  - Supports CLI flags for CI and developer verification.

Usage:
  python packages/sim/scripts/run_golden_benchmarks.py
  python packages/sim/scripts/run_golden_benchmarks.py --scenario flat-motor
  python packages/sim/scripts/run_golden_benchmarks.py --scenario flat-motor --mutate gravity:1.1
  python packages/sim/scripts/run_golden_benchmarks.py --scenario flat-motor --mutate stiffness:1.2 --expect-failure
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from strandbeest_sim import load_scenario, run

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = ROOT / "contracts" / "sim-golden" / "runs-contact-v3.json"
OBSERVATION_PATH = ROOT / "contracts" / "sim-golden" / "observation-v3.json"
DEFAULT_RTOL = 1e-7


def load_golden_catalog() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load the golden run corpus and peak/audit observation records."""
    if not GOLDEN_PATH.exists():
        raise FileNotFoundError(f"Golden run record not found: {GOLDEN_PATH}")
    if not OBSERVATION_PATH.exists():
        raise FileNotFoundError(f"Observation record not found: {OBSERVATION_PATH}")

    golden_runs = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["runs"]
    observations = {
        r["name"]: r
        for r in json.loads(OBSERVATION_PATH.read_text(encoding="utf-8"))["runs"]
    }
    return golden_runs, observations


def sample(a: Any, n: int = 24) -> list[float]:
    """Decimate a 1D time series to n evenly spaced points for comparison."""
    arr = np.asarray(a, float)
    idx = np.linspace(0, len(arr) - 1, n).round().astype(int)
    return [float(arr[i]) for i in idx]


def is_close(a: float | None, b: float | None, rtol: float = DEFAULT_RTOL, atol: float = 1e-12) -> bool:
    """Check if two floats match within relative and absolute tolerances."""
    if a is None or b is None:
        return a is None and (b is None or (isinstance(b, float) and math.isnan(b)))
    if math.isnan(a) and math.isnan(b):
        return True
    return bool(math.isclose(a, b, rel_tol=rtol, abs_tol=atol))


def apply_mutation(scenario_dict: dict[str, Any], mutation_spec: str) -> tuple[dict[str, Any], str]:
    """Apply a deliberate physical parameter perturbation to a scenario.

    Supported mutations:
      - 'gravity[:factor]' (default: 1.1) -> perturb environment.gravity
      - 'stiffness[:factor]' (default: 1.2) -> perturb solver.contact_stiffness
      - 'joint_friction[:value]' (default: 0.05) -> set walker.joint_friction
      - 'foot_friction[:factor]' (default: 0.8) -> perturb walker.foot_friction
      - 'terrain_friction[:factor]' (default: 0.8) -> perturb terrain.friction
      - 'damping[:factor]' (default: 1.5) -> perturb solver.contact_damping_ratio
      - 'default' -> gravity:1.1
    """
    sc = copy.deepcopy(scenario_dict)
    parts = mutation_spec.strip().split(":", 1)
    kind = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else None

    if kind in ("gravity", "g"):
        factor = float(arg) if arg is not None else 1.1
        env = sc.setdefault("environment", {})
        old_val = float(env.get("gravity", 9.81))
        new_val = old_val * factor
        env["gravity"] = new_val
        desc = f"environment.gravity: {old_val} -> {new_val} (factor {factor})"

    elif kind in ("stiffness", "contact_stiffness", "k"):
        factor = float(arg) if arg is not None else 1.2
        solver = sc.setdefault("solver", {})
        old_val = float(solver.get("contact_stiffness", 300000.0))
        new_val = old_val * factor
        solver["contact_stiffness"] = new_val
        desc = f"solver.contact_stiffness: {old_val} -> {new_val} (factor {factor})"

    elif kind in ("joint_friction", "pin_friction"):
        val = float(arg) if arg is not None else 0.05
        walker = sc.setdefault("walker", {})
        old_val = float(walker.get("joint_friction", 0.0))
        walker["joint_friction"] = val
        desc = f"walker.joint_friction: {old_val} -> {val}"

    elif kind in ("foot_friction", "friction"):
        factor = float(arg) if arg is not None else 0.8
        walker = sc.setdefault("walker", {})
        old_val = float(walker.get("foot_friction", 1.5))
        new_val = old_val * factor
        walker["foot_friction"] = new_val
        desc = f"walker.foot_friction: {old_val} -> {new_val} (factor {factor})"

    elif kind in ("terrain_friction",):
        factor = float(arg) if arg is not None else 0.8
        terrain = sc.setdefault("terrain", {})
        old_val = float(terrain.get("friction", 1.5))
        new_val = old_val * factor
        terrain["friction"] = new_val
        desc = f"terrain.friction: {old_val} -> {new_val} (factor {factor})"

    elif kind in ("damping", "contact_damping"):
        factor = float(arg) if arg is not None else 1.5
        solver = sc.setdefault("solver", {})
        old_val = float(solver.get("contact_damping_ratio", 1.0))
        new_val = old_val * factor
        solver["contact_damping_ratio"] = new_val
        desc = f"solver.contact_damping_ratio: {old_val} -> {new_val} (factor {factor})"

    elif kind == "default":
        return apply_mutation(sc, "gravity:1.1")

    else:
        raise ValueError(
            f"Unknown mutation type '{kind}'. Choose from gravity, stiffness, joint_friction, "
            f"foot_friction, terrain_friction, damping, default."
        )

    return sc, desc


def compare_run_against_golden(
    res: Any,
    golden_entry: dict[str, Any],
    observation_entry: dict[str, Any],
    rtol: float = DEFAULT_RTOL,
) -> list[str]:
    """Compare a simulation result against golden run metrics and samples.

    Returns a list of anomaly descriptions. An empty list means the run
    matches the golden baseline within tolerances.
    """
    diffs: list[str] = []

    # 1. Stalled state
    if bool(res.stalled) != bool(golden_entry["stalled"]):
        diffs.append(
            f"stalled flag mismatch: expected {golden_entry['stalled']}, got {res.stalled}"
        )

    # 2. Step count
    if len(res.t) != golden_entry["n"]:
        diffs.append(
            f"step count mismatch: expected {golden_entry['n']}, got {len(res.t)}"
        )

    # 3. Metrics (including observation peak metrics)
    expected_metrics = {
        **golden_entry["metrics"],
        **observation_entry.get("peak_metrics", {}),
    }
    for k, v in expected_metrics.items():
        actual = res.metrics.get(k)
        if not is_close(v, actual, rtol=rtol):
            rel_diff = (
                abs(actual - v) / (abs(v) + 1e-12)
                if actual is not None and v is not None
                else float("nan")
            )
            diffs.append(
                f"metric '{k}' mismatch: expected {v}, got {actual} (rel_diff={rel_diff:.4e} > {rtol})"
            )

    # 4. Audit observation
    obs_expected = observation_entry.get("audit_observation")
    if obs_expected is not None and hasattr(res, "audit_observation"):
        if res.audit_observation != obs_expected:
            mismatched_keys = [
                k
                for k, exp_val in obs_expected.items()
                if res.audit_observation.get(k) != exp_val
            ]
            diffs.append(
                f"audit_observation fields mismatch on {mismatched_keys}: "
                f"expected={obs_expected}, got={res.audit_observation}"
            )

    # 5. Samples (t, psi, x, z, torque)
    for channel, arr in (
        ("t", res.t),
        ("psi", res.psi),
        ("x", res.x),
        ("z", res.z),
        ("torque", res.torque),
    ):
        expected_samples = golden_entry.get("samples", {}).get(channel)
        if expected_samples is not None:
            actual_samples = sample(arr, len(expected_samples))
            for i, (exp_val, act_val) in enumerate(zip(expected_samples, actual_samples)):
                if not is_close(exp_val, act_val, rtol=rtol):
                    rel_diff = (
                        abs(act_val - exp_val) / (abs(exp_val) + 1e-12)
                        if act_val is not None and exp_val is not None
                        else float("nan")
                    )
                    diffs.append(
                        f"sample {channel}[{i}] mismatch: expected {exp_val}, got {act_val} "
                        f"(rel_diff={rel_diff:.4e} > {rtol})"
                    )

    # 6. Frames check
    if "frames" in golden_entry:
        f = res.frames
        if f is None:
            diffs.append("frames mismatch: expected frame data, got None")
        else:
            exp_frames = golden_entry["frames"]
            act_shape = (
                len(f["t"]),
                f["pos"].shape[1],
                int(f["contact"].sum()),
            )
            exp_shape = (
                exp_frames["count"],
                exp_frames["bodies"],
                exp_frames["contact_sum"],
            )
            if act_shape != exp_shape:
                diffs.append(
                    f"frames dimensions/contact mismatch: expected {exp_shape}, got {act_shape}"
                )
            pos_sum = float(np.round(f["pos"].astype(np.float64).sum(), 4))
            if not is_close(exp_frames["pos_sum"], pos_sum, rtol=1e-4, atol=1e-4):
                diffs.append(
                    f"frames pos_sum mismatch: expected {exp_frames['pos_sum']}, got {pos_sum}"
                )

    return diffs


def run_benchmark(
    scenario_filter: str | None = None,
    mutation_spec: str | None = None,
    rtol: float = DEFAULT_RTOL,
    expect_failure: bool = False,
    verbose: bool = True,
) -> tuple[int, dict[str, Any]]:
    """Run golden benchmarks and check regression / mutation sensitivity."""
    golden_runs, observations = load_golden_catalog()

    if scenario_filter:
        golden_runs = [g for g in golden_runs if g["name"] == scenario_filter]
        if not golden_runs:
            print(f"Error: Scenario '{scenario_filter}' not found in golden corpus.")
            return 2, {"error": f"Scenario '{scenario_filter}' not found"}

    results: list[dict[str, Any]] = []
    overall_success = True

    for g in golden_runs:
        name = g["name"]
        scenario_doc = g["scenario"]
        obs_entry = observations.get(name, {})

        mutation_desc = None
        if mutation_spec:
            scenario_doc, mutation_desc = apply_mutation(scenario_doc, mutation_spec)

        if verbose:
            mut_info = f" [mutation: {mutation_desc}]" if mutation_desc else ""
            print(f"Running golden scenario: {name}{mut_info} ...", end=" ", flush=True)

        sc = load_scenario(scenario_doc)
        res = run(sc)

        diffs = compare_run_against_golden(res, g, obs_entry, rtol=rtol)

        has_regression = len(diffs) > 0

        if mutation_spec and expect_failure:
            # Under mutation testing, regression failure IS expected
            scenario_ok = has_regression
            status_str = "MUTATION_DETECTED" if has_regression else "MUTATION_MISSED"
        else:
            scenario_ok = not has_regression
            status_str = "PASSED" if not has_regression else "REGRESSION_FAILED"

        if not scenario_ok:
            overall_success = False

        if verbose:
            print(f"[{status_str}]")
            if diffs and (not expect_failure or not scenario_ok):
                print(f"  Differences found ({len(diffs)} total):")
                for d in diffs[:5]:
                    print(f"    - {d}")
                if len(diffs) > 5:
                    print(f"    ... and {len(diffs) - 5} more differences")

        results.append({
            "name": name,
            "status": status_str,
            "ok": scenario_ok,
            "mutation": mutation_desc,
            "diff_count": len(diffs),
            "diffs": diffs[:10],
        })

    report = {
        "overall_success": overall_success,
        "scenarios_tested": len(results),
        "mutation_spec": mutation_spec,
        "expect_failure": expect_failure,
        "rtol": rtol,
        "runs": results,
    }

    exit_code = 0 if overall_success else 1
    return exit_code, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run golden simulator benchmarks and mutation sensitivity tests (Q-01)."
    )
    parser.add_argument(
        "--scenario",
        "-s",
        type=str,
        default=None,
        help="Filter by golden scenario name (e.g. flat-motor, slope-5deg).",
    )
    parser.add_argument(
        "--mutate",
        "-m",
        type=str,
        nargs="?",
        const="default",
        default=None,
        help="Apply perturbation (e.g. gravity:1.1, stiffness:1.2, joint_friction:0.05).",
    )
    parser.add_argument(
        "--expect-failure",
        action="store_true",
        help="Assert that regression checks fail when mutations are applied (exits 0 if detected, 1 if missed).",
    )
    parser.add_argument(
        "--rtol",
        type=float,
        default=DEFAULT_RTOL,
        help=f"Relative tolerance for golden numerical comparison (default: {DEFAULT_RTOL}).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available golden scenarios and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress verbose scenario output.",
    )

    args = parser.parse_args(argv)

    if args.list:
        golden_runs, _ = load_golden_catalog()
        print("Available golden scenarios:")
        for r in golden_runs:
            print(f"  - {r['name']}")
        return 0

    exit_code, report = run_benchmark(
        scenario_filter=args.scenario,
        mutation_spec=args.mutate,
        rtol=args.rtol,
        expect_failure=args.expect_failure,
        verbose=not args.quiet and not args.json,
    )

    if args.json:
        print(json.dumps(report, indent=2))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
