"""Invariant and boundary condition tests for MAP-Elites quality-diversity archive."""

import json
import math
from pathlib import Path
import numpy as np
from strandbeest_opt.qd import MapElites, _bin

ROOT = Path(__file__).resolve().parents[3]
BASE = json.loads((ROOT / "schemas" / "examples" / "design-jansen-small-6leg.json").read_text())


def test_bin_nan_and_infinite_boundary_immunity():
    """_bin must strictly return None for NaN, Inf, and exact outer boundaries."""
    edges = np.linspace(0.0, 1.0, 11)  # 10 bins: [0.0, 0.1), ..., [0.9, 1.0)
    
    # Non-finite values
    assert _bin(float("nan"), edges) is None
    assert _bin(float("inf"), edges) is None
    assert _bin(-float("inf"), edges) is None
    
    # Boundary values
    assert _bin(-0.0001, edges) is None
    assert _bin(1.0, edges) is None  # Upper edge is strictly half-open
    assert _bin(1.0001, edges) is None
    
    # Valid lower edge and internal values
    assert _bin(0.0, edges) == 0
    assert _bin(0.05, edges) == 0
    assert _bin(0.95, edges) == 9
    assert _bin(0.9999, edges) == 9


def test_map_elites_pareto_front_mutual_non_dominance():
    """All individuals on the Pareto front must be mutually non-dominated."""
    me = MapElites(
        BASE,
        seed=42,
        grid_shape=(6, 6),
        feature_descriptors=("lift_ratio", "cost_of_transport"),
    )
    me.run(evals=80)
    front = me.pareto_front()
    
    assert len(front) > 0
    
    # Verify no two elites in front dominate one another
    for i, a in enumerate(front):
        for j, b in enumerate(front):
            if i == j:
                continue
            # A dominates B if A is no worse than B in all objectives and strictly better in at least one
            # Objectives: maximize fitness, maximize lift_ratio, minimize cost_of_transport
            a_no_worse = (
                a.fitness >= b.fitness
                and a.lift_ratio >= b.lift_ratio
                and a.cost_of_transport <= b.cost_of_transport
            )
            a_strictly_better = (
                a.fitness > b.fitness
                or a.lift_ratio > b.lift_ratio
                or a.cost_of_transport < b.cost_of_transport
            )
            a_dominates_b = a_no_worse and a_strictly_better
            assert not a_dominates_b, f"Pareto front contains dominated solution: {a} dominates {b}"
