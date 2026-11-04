"""Independent signed multi-leg reference study; never changes the live audit.

Assumption: a nonrotating torso rides on the lowest foot centres. A declared
height tolerance selects candidate supports. Equal weighting is a least-
squares convention, not a claim that incompatible supports can all avoid slip.
Report their incompatibility explicitly. No ratio denominator is enlarged.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Callable, Sequence

from strandbeest_common import load_spec, solve_pose
from strandbeest_sim.config import sim_config


def fit_support(foot_velocities: Sequence[float]) -> dict:
    """No-slip equations are V + u_i = 0; equal-weight least-squares V."""
    if not foot_velocities:
        return {"velocity": None, "rms_slip": None, "spread": None}
    velocity = -sum(foot_velocities) / len(foot_velocities)
    rms = math.sqrt(sum((velocity + v)**2 for v in foot_velocities) / len(foot_velocities))
    return {"velocity": velocity, "rms_slip": rms,
            "spread": max(foot_velocities) - min(foot_velocities)}


def cycle_reference(foot: Callable[[float], tuple[float, float]], *, phases: Sequence[float], direction: int,
                    unit: float, support_tolerance: float, samples: int, derivative_step: float) -> dict:
    distance = squared_slip = 0.0
    max_spread = 0.0
    max_supports = 0
    for i in range(samples):
        angle = 2 * math.pi * i / samples
        positions = [foot(angle + phase) for phase in phases]
        if not positions:
            return {"stride": None, "rms_slip": None, "max_spread": None, "max_supports": 0}
        lowest = min(p[1] for p in positions)
        supports = [j for j, p in enumerate(positions) if p[1] <= lowest + support_tolerance]
        velocities = [direction * unit * (foot(angle + phases[j] + derivative_step)[0]
                                         - foot(angle + phases[j] - derivative_step)[0]) / (2 * derivative_step)
                      for j in supports]
        fit = fit_support(velocities)
        distance += fit["velocity"] * 2 * math.pi / samples
        squared_slip += fit["rms_slip"]**2 / samples
        max_spread = max(max_spread, fit["spread"])
        max_supports = max(max_supports, len(supports))
    return {"stride": distance, "rms_slip": math.sqrt(squared_slip),
            "max_spread": max_spread, "max_supports": max_supports}


def lowest_foot_stride(foot: Callable[[float], tuple[float, float]], *, phases: Sequence[float],
                       direction: int, unit: float, brackets: int) -> dict:
    """Integrate each support interval by endpoint displacement, not derivatives.

    Locate switches of the lowest foot by bisection. Bracket-count convergence
    is reported independently, so an unresolved near-zero cycle is visible.
    """
    if not phases:
        return {"stride": None, "switches": 0}
    def support(theta):
        return min(range(len(phases)), key=lambda j: foot(theta + phases[j])[1])
    boundaries = [0.]
    last = support(0.)
    for i in range(1, brackets + 1):
        a, b = 2 * math.pi * (i - 1) / brackets, 2 * math.pi * i / brackets
        following = support(b)
        if following != last:
            left = last
            for _ in range(48):
                midpoint = (a + b) * .5
                if support(midpoint) == left:
                    a = midpoint
                else:
                    b = midpoint
            boundaries.append((a + b) * .5)
        last = following
    boundaries.append(2 * math.pi)
    stride = 0.
    for a, b in zip(boundaries, boundaries[1:]):
        leg = support((a + b) * .5)
        stride -= direction * unit * (foot(b + phases[leg])[0] - foot(a + phases[leg])[0])
    return {"stride": stride, "switches": len(boundaries) - 2}


def analytic_checks():
    # A single support and compatible repeated supports have an exact solution.
    assert fit_support([-2.0])["velocity"] == 2.0
    assert fit_support([2.0, 2.0])["velocity"] == -2.0
    # A zero fitted velocity does not make incompatible supports no-slip.
    opposed = fit_support([-2.0, 2.0])
    assert opposed == {"velocity": 0.0, "rms_slip": 2.0, "spread": 4.0}
    assert fit_support([])["velocity"] is None
    rows = []
    # For N evenly phased elliptical feet x=A*cos(theta), y=sin(theta),
    # the lowest-foot no-slip integral is -direction*2*N*A*sin(pi/N).
    # Includes forward, reverse, zero and tiny nonzero signed strides.
    for n, direction, amplitude in ((2, -1, 1.), (2, 1, 1.), (4, -1, 1.),
                                     (4, 1, 1.), (2, -1, 0.), (2, 1, 1e-10)):
        result = cycle_reference(lambda a: (amplitude * math.cos(a), math.sin(a)),
                                 phases=[2 * math.pi * k / n for k in range(n)], direction=direction,
                                 unit=1., support_tolerance=0., samples=7200, derivative_step=1e-5)
        expected = -direction * 2 * n * amplitude * math.sin(math.pi / n)
        assert abs(result["stride"] - expected) <= abs(expected) * 1e-6 + 1e-20
        endpoint = lowest_foot_stride(lambda a: (amplitude * math.cos(a), math.sin(a)),
                                     phases=[2 * math.pi * k / n for k in range(n)], direction=direction,
                                     unit=1., brackets=72)
        assert abs(endpoint["stride"] - expected) <= abs(expected) * 1e-12 + 1e-24
        rows.append({"legs": n, "direction": direction, "amplitude": amplitude,
                     "expected_stride": expected, "actual": result, "endpoint": endpoint})
    return rows


def main():
    output = Path(sys.argv[1])
    if output.exists():
        raise FileExistsError(output)
    source = json.loads(Path(sys.argv[2]).read_text())
    selected = {20, 53, 56, 61}
    rows = []
    for row in source["rows"]:
        if row["case"] not in selected:
            continue
        sc = sim_config(row["scenario"])
        spec = load_spec(sc.linkage.spec)
        w = sc.walker.model_dump(mode="json")
        foot = lambda angle: solve_pose(spec, angle)[spec.foot]
        # Two declared assumptions, not a tuning search: exact lowest foot,
        # and the established TS quasi-static model's one-length-unit band.
        estimates = []
        for tolerance in (0., 1.):
            for samples in (720, 1440):
                reference = cycle_reference(foot, phases=[2 * math.pi * k / w["legs"] for k in range(w["legs"])],
                                            direction=w["direction"], unit=w["unit"], support_tolerance=tolerance,
                                            samples=samples, derivative_step=1e-5)
                estimates.append({"support_tolerance_units": tolerance, "samples": samples, **reference})
        rows.append({"case": row["case"], "spec": sc.linkage.spec, "walker": w, "observed_stride": row["metrics"]["stride_per_rev"],
                     "old_findings": row["findings"], "references": estimates,
                     "endpoint_references": [{"brackets": count, **lowest_foot_stride(
                         foot, phases=[2 * math.pi * k / w["legs"] for k in range(w["legs"])],
                         direction=w["direction"], unit=w["unit"], brackets=count)} for count in (720, 1440, 2880)]})
    doc = {"definition": __doc__, "analytic_checks": analytic_checks(), "rows": rows,
           "changes_live_audit": False, "passes_original_g1_gate": False}
    with output.open("x") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    for row in rows:
        print(row["case"], row["observed_stride"], row["endpoint_references"], flush=True)


if __name__ == "__main__":
    main()
