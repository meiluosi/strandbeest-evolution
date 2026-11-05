"""Tests for V-04 design ranking stability analysis (packages/opt/stability.py)."""

import math
import pytest
from strandbeest_opt.stability import (
    StabilityThresholds,
    analyze_multiseed_stability,
    check_ranking_stability,
    confidence_interval,
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


def test_confidence_interval_calculation():
    # Empty and single-element edge cases
    assert confidence_interval([]) == (0.0, 0.0, 0.0, 0.0)
    assert confidence_interval([5.0]) == (5.0, 0.0, 5.0, 5.0)

    # Identical values -> std=0, bounds collapse to mean
    m, s, lo, hi = confidence_interval([3.0, 3.0, 3.0, 3.0])
    assert m == 3.0
    assert s == 0.0
    assert lo == 3.0
    assert hi == 3.0

    # Distinct sample
    data = [10.0, 12.0, 11.0, 9.0, 10.5, 11.5]
    mean, std, ci_lo, ci_hi = confidence_interval(data, confidence=0.95)
    assert abs(mean - (sum(data) / len(data))) < 1e-9
    assert ci_lo < mean < ci_hi
    assert std > 0.0


def test_analyze_multiseed_stability_passing_case():
    thresh = StabilityThresholds(min_spearman=0.70, min_top_k_overlap=0.60, max_failure_rate=0.05)
    # 3 seeds with near-identical rankings
    seed_records = [
        {
            "seed": 1,
            "mujoco_scores": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "k2_scores": [9.9, 9.1, 7.9, 7.1, 6.0, 4.9, 4.1, 2.9, 2.0, 1.1],
            "mujoco_failures": [False] * 10,
            "k2_failures": [False] * 10,
        },
        {
            "seed": 2,
            "mujoco_scores": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "k2_scores": [9.8, 8.9, 8.1, 6.9, 6.1, 5.1, 3.9, 3.1, 1.9, 1.0],
            "mujoco_failures": [False] * 10,
            "k2_failures": [False] * 10,
        },
    ]

    res = analyze_multiseed_stability(seed_records, thresholds=thresh, top_k=5)
    assert res.is_stable is True
    assert res.is_verified_winner is True
    assert len(res.passed_seeds) == 2
    assert len(res.failed_seeds) == 0
    assert res.pooled_spearman > 0.95
    assert res.pooled_top_k_overlap >= 0.80
    assert "STABLE" in res.verdict


def test_analyze_multiseed_stability_rejection_on_instability():
    thresh = StabilityThresholds(min_spearman=0.70, min_top_k_overlap=0.60, max_failure_rate=0.05)
    # Seeds with rank flips / low correlation
    seed_records = [
        {
            "seed": 1,
            "mujoco_scores": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "k2_scores": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],  # reversed!
            "mujoco_failures": [False] * 10,
            "k2_failures": [False] * 10,
        },
        {
            "seed": 2,
            "mujoco_scores": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "k2_scores": [5.0, 10.0, 1.0, 8.0, 2.0, 7.0, 3.0, 6.0, 4.0, 9.0],  # jumbled
            "mujoco_failures": [False] * 10,
            "k2_failures": [False] * 10,
        },
    ]

    res = analyze_multiseed_stability(seed_records, thresholds=thresh, top_k=5)
    assert res.is_stable is False
    assert res.is_verified_winner is False  # Must NOT be output as verified winner!
    assert len(res.failed_seeds) == 2
    assert "UNSTABLE (REJECTED)" in res.verdict
    assert "cannot be output as verified winners" in res.verdict


def test_analyze_multiseed_stability_failure_rate_gating():
    thresh = StabilityThresholds(min_spearman=0.70, min_top_k_overlap=0.60, max_failure_rate=0.05)
    # Good correlation, but high failure rate
    seed_records = [
        {
            "seed": 1,
            "mujoco_scores": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "k2_scores": [9.9, 9.1, 7.9, 7.1, 6.0, 4.9, 4.1, 2.9, 2.0, 1.1],
            "mujoco_failures": [False] * 10,
            "k2_failures": [True, True, False, False, False, False, False, False, False, False],  # 20% fail > 5%
        }
    ]
    res = analyze_multiseed_stability(seed_records, thresholds=thresh, top_k=5)
    assert res.is_stable is False
    assert res.is_verified_winner is False
    assert 1 in res.failed_seeds
