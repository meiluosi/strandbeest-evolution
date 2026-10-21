"""Tests for V-04 design ranking stability analysis (packages/opt/stability.py)."""

import math
import pytest
from strandbeest_opt.stability import (
    check_ranking_stability,
    evaluate_stability_suite,
    rank_descending,
    spearman_rank_correlation,
    top_k_overlap,
)


def test_rank_descending_and_ties():
    scores = [10.0, 50.0, 30.0, 30.0, 5.0]
    # 50.0 is rank 1, 30.0 are tied for ranks 2 and 3 -> avg 2.5, 10.0 is rank 4, 5.0 is rank 5
    ranks = rank_descending(scores)
    assert ranks == [4.0, 1.0, 2.5, 2.5, 5.0]


def test_spearman_rank_correlation_properties():
    # Identity
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert abs(spearman_rank_correlation(a, a) - 1.0) < 1e-9

    # Reverse
    b = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert abs(spearman_rank_correlation(a, b) - (-1.0)) < 1e-9

    # Monotonic non-linear transform preserves ranking
    c = [math.exp(x) for x in a]
    assert abs(spearman_rank_correlation(a, c) - 1.0) < 1e-9

    # Compare against scipy if installed
    try:
        from scipy.stats import spearmanr

        s1 = [12.5, 8.2, 19.1, 4.0, 7.3, 15.6, 11.0]
        s2 = [11.8, 8.9, 18.5, 5.2, 7.1, 14.9, 12.1]
        scipy_val = float(spearmanr(s1, s2).statistic)
        my_val = spearman_rank_correlation(s1, s2)
        assert abs(scipy_val - my_val) < 1e-9
    except ImportError:
        pass


def test_top_k_overlap():
    a = [10, 9, 8, 7, 6, 5, 4]
    b = [10, 9, 8, 7, 6, 3, 2]  # top 5 identical
    jaccard, ratio, top_a, top_b = top_k_overlap(a, b, k=5)
    assert top_a == [0, 1, 2, 3, 4]
    assert top_b == [0, 1, 2, 3, 4]
    assert jaccard == 1.0
    assert ratio == 1.0

    c = [1, 2, 3, 4, 5, 6, 7]  # completely reversed
    jaccard_rev, ratio_rev, _, _ = top_k_overlap(a, c, k=3)
    assert jaccard_rev == 0.0
    assert ratio_rev == 0.0


def test_check_ranking_stability_report():
    scores = {
        "cond_a": [10.0, 8.0, 6.0, 4.0, 2.0, 1.0],
        "cond_b": [9.8, 8.2, 5.9, 4.1, 1.9, 1.1],  # highly correlated
        "cond_c": [1.0, 2.0, 4.0, 6.0, 8.0, 10.0],  # flipped
    }
    report = check_ranking_stability(scores, k=3)

    assert report.n_designs == 6
    assert report.top_k == 3
    assert report.spearman_matrix["cond_a"]["cond_b"] > 0.95
    assert report.spearman_matrix["cond_a"]["cond_c"] < -0.95
    assert report.is_stable is False  # cond_c flips ranking
    assert len(report.unstable_pairs) >= 1

    summary = report.summary_table()
    assert "Pairwise Spearman Rank Correlation Matrix" in summary
    assert "cond_a" in summary


def test_evaluate_stability_suite_integration():
    """Fast integration test verifying evaluate_stability_suite on 2 designs."""
    import copy
    from strandbeest_sim.contract import _example_design

    d0 = _example_design()
    d1 = copy.deepcopy(d0)
    d1["linkage"]["params"]["m"] = 13.0  # smaller crank -> distinct stride

    designs = [d0, d1]
    conditions = {
        "k2_stride": {"backend": "k2", "metric": "stride_per_rev"},
        "kinematic_stroke": {"backend": "kinematic", "metric": "stroke_length"},
    }

    report = evaluate_stability_suite(designs, conditions, k=2)
    assert len(report.scores["k2_stride"]) == 2
    assert len(report.scores["kinematic_stroke"]) == 2
    assert "k2_stride" in report.spearman_matrix
