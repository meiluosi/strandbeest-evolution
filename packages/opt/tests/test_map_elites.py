"""Tests for M8-01: Quality-Diversity MAP-Elites with 2D behavior feature descriptors.

Acceptance criteria:
  - Cell binning over continuous behavior spaces (lift ratio, transport cost).
  - Iso+LineDD proposal operator (line mutation + isotropic noise).
  - Elite replacement semantics (best per cell kept).
  - QD-score monotonicity (sum of fitness never decreases).
  - Species atlas serialization and JSON schema validation.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from strandbeest_common import Design
from strandbeest_common.schemas import validate
from strandbeest_opt.qd import (
    IsoLineDDCrossover,
    MapElites,
    _bin,
    compute_cost_of_transport,
    compute_lift_ratio,
    describe_features,
)
from strandbeest_opt.space import GenomeSpace

ROOT = Path(__file__).resolve().parents[3]
BASE = json.loads((ROOT / "schemas" / "examples" / "design-jansen-small-6leg.json").read_text())


# 1. Cell binning tests
def test_cell_binning():
    edges = np.linspace(0.1, 0.5, 5)  # 4 bins: [0.1, 0.2), [0.2, 0.3), [0.3, 0.4), [0.4, 0.5)
    assert _bin(0.05, edges) is None  # below min
    assert _bin(0.55, edges) is None  # above max
    assert _bin(0.50, edges) is None  # upper boundary exclusive
    assert _bin(0.10, edges) == 0
    assert _bin(0.19, edges) == 0
    assert _bin(0.20, edges) == 1
    assert _bin(0.35, edges) == 2
    assert _bin(0.49, edges) == 3

    # Real 2D descriptor evaluation and binning
    space = GenomeSpace.of(BASE["linkage"])
    genome = space.to_genome()
    feats = describe_features(BASE, space, genome, 6, ("lift_ratio", "cost_of_transport"))
    assert feats is not None
    assert 0.15 < feats["lift_ratio"] < 0.60
    assert 0.005 < feats["cost_of_transport"] < 0.50

    me = MapElites(
        BASE,
        seed=42,
        feature_descriptors=("lift_ratio", "cost_of_transport"),
        grid_shape=(10, 10),
        feature_ranges={"lift_ratio": (0.1, 0.6), "cost_of_transport": (0.01, 0.4)},
    )
    b_lift = _bin(feats["lift_ratio"], me.bin_edges["lift_ratio"])
    b_cot = _bin(feats["cost_of_transport"], me.bin_edges["cost_of_transport"])
    assert b_lift is not None and 0 <= b_lift < 10
    assert b_cot is not None and 0 <= b_cot < 10


# 2. Iso+LineDD proposal tests
def test_isoline_dd_proposal():
    import random

    rng = random.Random(123)
    crossover = IsoLineDDCrossover(sigma_iso=0.01, sigma_line=0.25, rng=rng)

    p1 = [10.0, 20.0, 30.0, 40.0]
    p2 = [20.0, 20.0, 30.0, 40.0]  # differs only in dimension 0 by +10.0
    bounds = [(5.0, 50.0)] * 4

    # Single parent fallback: isotropic mutation
    single_child = crossover.propose(p1, None, bounds=bounds)
    assert len(single_child) == 4
    for a, c in zip(p1, single_child):
        assert abs(c - a) < 1.0  # small isotropic step

    # Two parents: line mutation along (p2 - p1)
    samples = [crossover.propose(p1, p2, bounds=bounds) for _ in range(500)]

    # Dimension 0 (line direction) should have significantly higher variance than dimension 1 (pure isotropic)
    dim0_diffs = [s[0] - p1[0] for s in samples]
    dim1_diffs = [s[1] - p1[1] for s in samples]
    var_dim0 = float(np.var(dim0_diffs))
    var_dim1 = float(np.var(dim1_diffs))

    # Variance along the line direction must dominate orthogonal isotropic variance
    assert var_dim0 > 5 * var_dim1
    assert var_dim1 > 0.0

    # Bounds clamping respected
    tight_bounds = [(9.0, 11.0), (19.0, 21.0), (29.0, 31.0), (39.0, 41.0)]
    clamped = crossover.propose([10.0, 20.0, 30.0, 40.0], [50.0, 50.0, 50.0, 50.0], bounds=tight_bounds)
    for v, (lo, hi) in zip(clamped, tight_bounds):
        assert lo <= v <= hi


# 3. Elite replacement semantics
def test_elite_replacement():
    me = MapElites(
        BASE,
        seed=7,
        feature_descriptors=("lift_ratio", "cost_of_transport"),
        grid_shape=(12, 12),
        feature_ranges={"lift_ratio": (0.15, 0.65), "cost_of_transport": (0.01, 0.40)},
    )
    g0 = me.space.to_genome()

    # Consider baseline individual
    inserted = me.consider(g0)
    assert inserted is True
    assert len(me.archive) == 1
    cell = next(iter(me.archive.keys()))
    elite0 = me.archive[cell]
    assert elite0.fitness > 0

    # Re-considering the exact same genome cannot beat itself
    assert me.consider(g0) is False
    assert len(me.archive) == 1
    assert me.archive[cell].born == elite0.born

    # Proposal with lower fitness in the same cell is rejected
    # Infeasible or broken leg has fitness <= 0 and is rejected
    bad_genome = [0.001] * len(g0)
    assert me.consider(bad_genome) is False
    assert me.archive[cell] == elite0


# 4. QD-score monotonicity and archive filling
def test_qd_score_monotonicity():
    me = MapElites(
        BASE,
        seed=42,
        feature_descriptors=("lift_ratio", "cost_of_transport"),
        grid_shape=(14, 14),
        feature_ranges={"lift_ratio": (0.15, 0.65), "cost_of_transport": (0.01, 0.35)},
    )

    # Run for 1200 evaluations
    me.run(1200, log_every=100)
    assert len(me.archive) >= 15

    # Check that QD score curve is strictly monotonic non-decreasing
    qd_curve = [c[2] for c in me.curve]
    cells_curve = [c[1] for c in me.curve]

    assert len(qd_curve) >= 10
    assert qd_curve == sorted(qd_curve), f"QD-score decreased! {qd_curve}"
    assert cells_curve == sorted(cells_curve), f"Filled cells decreased! {cells_curve}"

    # Verify coverage calculation
    expected_coverage = len(me.archive) / (14 * 14)
    assert me.coverage == pytest.approx(expected_coverage, rel=1e-5)
    assert me.qd_score == pytest.approx(sum(e.fitness for e in me.archive.values()), rel=1e-5)


# 5. Species atlas serialization and Pareto front
def test_species_atlas_export_and_validation(tmp_path):
    me = MapElites(
        BASE,
        seed=11,
        feature_descriptors=("lift_ratio", "cost_of_transport"),
        grid_shape=(10, 10),
        feature_ranges={"lift_ratio": (0.15, 0.65), "cost_of_transport": (0.01, 0.40)},
    )
    me.run(600, log_every=100)

    # Pareto front extraction
    pareto = me.pareto_front()
    assert len(pareto) >= 1
    for p in pareto:
        assert p.cell in me.archive
        assert p.fitness > 0

    # SpeciesAtlas serialization
    atlas = me.to_atlas()
    assert atlas["schema_version"] == 2
    assert atlas["kind"] == "species_atlas"
    assert atlas["dimensions"] == 2
    assert atlas["features"] == ["lift_ratio", "cost_of_transport"]
    assert len(atlas["cells"]) == len(me.archive)
    assert atlas["qd_score"] == pytest.approx(me.qd_score, rel=1e-5)

    # Validate against JSON schema
    validate("atlas", atlas)

    # Export to disk and verify readability
    atlas_path = tmp_path / "species-atlas.json"
    me.export_atlas(atlas_path)
    assert atlas_path.exists()
    loaded = json.loads(atlas_path.read_text())
    validate("atlas", loaded)

    # Verify that every elite's design is fully valid and loadable
    for c in loaded["cells"][:5]:
        d = c["design"]
        Design(d)  # validates against design schema
        assert d["parent"]["id"] == BASE["id"]
        assert d["walker"]["legs"] == BASE["walker"]["legs"]
