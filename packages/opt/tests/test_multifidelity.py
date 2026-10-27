"""Tests for the two-tier multi-fidelity screen (O-03, packages/opt/multifidelity.py).

The fast tests use fake evaluators: they check the *logic* of the pipeline (promotion, the min_keep floor, the
agreement statistics, determinism) without any physics. The tests that need the simulator are marked `slow` and are
skipped by the fast suite (`-m "not slow"`).
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest
from strandbeest_opt import multifidelity
from strandbeest_opt.multifidelity import (
    agreement,
    coarse_kinematic_score,
    design_variants,
    discard_sweep,
    make_coarse_evaluator,
    make_fine_evaluator,
    retention_of_true_top_k,
    screen_two_stage,
    select_survivors,
)

BASE = json.loads(
    (Path(__file__).resolve().parents[3] / "schemas" / "examples" / "design-jansen-small-6leg.json").read_text()
)


def _fake_tiers(coarse, fine):
    """Two evaluators over index-carrying candidates."""
    return (
        lambda cand: float(coarse[cand]),
        lambda cand: float(fine[cand]),
    )


# ---------------------------------------------------------------------------------------
# the pipeline keeps the fine tier's winners
# ---------------------------------------------------------------------------------------
def test_the_two_stage_filter_keeps_the_fine_tier_top_five():
    # 12 candidates; the coarse tier ranks them like the fine tier except that ranks 4 and 5 are swapped
    coarse = [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    fine = [12, 11, 10, 9, 7, 8, 6, 5, 4, 3, 2, 1]
    c_eval, f_eval = _fake_tiers(coarse, fine)

    report = screen_two_stage(list(range(12)), c_eval, f_eval, keep=6, top_k=5, seed=1)

    # the fine tier only ever saw the 6 coarse survivors
    assert report.n_candidates == 12
    assert len(report.survivors) == 6
    assert report.n_discarded == 6
    assert report.discard_ratio == 0.5
    assert report.fine_scores[6] is None  # a discarded candidate carries no fine score
    # the fine tier's own top five are inside the survivor set
    assert report.fine_order[:5] == [0, 1, 2, 3, 5]
    # and the screen kept all five of the *true* fine top five
    kept = retention_of_true_top_k(coarse, fine, keep=6, top_k=5, seed=1)
    assert kept["retained_count"] == 5
    assert kept["retains_all"] is True
    assert kept["discard_ratio"] == 0.5


def test_the_survivors_are_the_coarse_tier_winners():
    coarse = [1, 5, 3, 9, 7]
    fine = [10, 1, 2, 3, 4]
    c_eval, f_eval = _fake_tiers(coarse, fine)

    report = screen_two_stage(list(range(5)), c_eval, f_eval, keep=2, top_k=2, seed=0)
    assert report.survivors == [3, 4]  # the two highest coarse scores, in coarse-rank order
    assert report.coarse_order == [3, 4, 1, 2, 0]
    assert report.fine_order == [4, 3]  # the fine tier may reorder the survivors
    assert report.fine_scores[0] is None


# ---------------------------------------------------------------------------------------
# a broken or degenerate coarse filter can never return nothing
# ---------------------------------------------------------------------------------------
def test_a_degenerate_coarse_filter_still_promotes_candidates():
    # every coarse score identical: the filter carries no information at all
    c_eval, f_eval = _fake_tiers([7, 7, 7, 7, 7, 7], [1, 2, 3, 4, 5, 6])
    report = screen_two_stage(list(range(6)), c_eval, f_eval, keep=3, min_keep=2, top_k=2, seed=0)
    assert len(report.survivors) == 3
    assert report.fine_timing.n_evaluations == 3
    # the survivors are re-ranked by the fine tier (which three of the tied candidates were promoted is up to the seed)
    fine_along_order = [report.fine_scores[i] for i in report.fine_order]
    assert fine_along_order == sorted(fine_along_order, reverse=True)


def test_the_min_keep_floor_survives_a_coarse_filter_that_raises():
    def broken(_cand):
        raise RuntimeError("the coarse solver exploded")

    fine_scores = [1.0, 2.0, 3.0]
    report = screen_two_stage(list(range(3)), broken, lambda c: fine_scores[c], keep=0, min_keep=2, top_k=2, seed=0)

    assert len(report.survivors) == 2  # the floor, not the requested keep=0
    assert report.n_discarded == 1
    assert any("coarse evaluation failed" in n for n in report.notes)
    assert report.coarse_timing.n_evaluations == 3  # every candidate was still tried


def test_select_survivors_honours_the_floor_and_never_returns_more_than_the_candidate_count():
    assert select_survivors([1, 2, 3], keep=0, min_keep=2)[0] == [2, 1]
    assert len(select_survivors([1, 2, 3], keep=10, min_keep=1)[0]) == 3
    assert select_survivors([], keep=3)[0] == []


def test_a_failing_fine_evaluation_is_reported_and_scored_worst_not_dropped():
    def fine(cand):
        if cand == 1:
            raise RuntimeError("the solver blew up")
        return float(10 - cand)

    c_eval = lambda cand: float(10 - cand)  # noqa: E731
    report = screen_two_stage(list(range(3)), c_eval, fine, keep=3, top_k=3, seed=0)
    assert len(report.survivors) == 3
    assert any("fine evaluation failed" in n for n in report.notes)
    assert report.fine_order[-1] == 1  # the failed candidate is the worst, not missing


# ---------------------------------------------------------------------------------------
# the statistics
# ---------------------------------------------------------------------------------------
def test_the_reported_spearman_matches_a_hand_computation():
    # hand computed: ranks of the coarse series are 1,2,3,4,5 and of the fine series 1,2,4,3,5
    # Pearson of (-2,-1,0,1,2) and (-2,-1,1,0,2) is 9/10 = 0.9
    coarse = [10, 9, 8, 7, 6]
    fine = [10, 9, 7, 8, 6]
    c_eval, f_eval = _fake_tiers(coarse, fine)

    report = screen_two_stage(list(range(5)), c_eval, f_eval, keep=5, top_k=3, seed=0)
    assert abs(report.spearman - 0.9) < 1e-12

    # the same number straight from the agreement helper
    a = agreement(coarse, fine, top_k=3)
    assert abs(a["spearman"] - 0.9) < 1e-12
    assert a["top_3_overlap"] == pytest.approx(2 / 3)  # the two series share two of their top three


def test_the_top_k_overlap_is_the_shared_fraction_of_the_two_layers():
    coarse = [10, 9, 8, 7, 6, 5]
    fine = [10, 9, 7, 8, 5, 6]  # the top two agree, ranks 3 and 4 are swapped
    c_eval, f_eval = _fake_tiers(coarse, fine)
    report = screen_two_stage(list(range(6)), c_eval, f_eval, keep=6, top_k=2, seed=0)
    assert report.top_k_overlap == 1.0
    assert report.top_k_coarse == ["c000", "c001"]
    assert report.top_k_fine == ["c000", "c001"]


def test_agreement_rejects_mismatched_series():
    with pytest.raises(ValueError):
        agreement([1, 2, 3], [1, 2])


# ---------------------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------------------
def test_the_selection_is_deterministic_under_a_fixed_seed():
    # three candidates tie for the last promotion slot
    coarse = [10.0, 9.0, 8.0, 8.0, 8.0, 8.0]
    fine = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    c_eval, f_eval = _fake_tiers(coarse, fine)

    a = screen_two_stage(list(range(6)), c_eval, f_eval, keep=3, top_k=3, seed=7)
    b = screen_two_stage(list(range(6)), c_eval, f_eval, keep=3, top_k=3, seed=7)
    assert a.survivors == b.survivors
    assert a.fine_order == b.fine_order
    assert a.spearman == b.spearman

    c = screen_two_stage(list(range(6)), c_eval, f_eval, keep=3, top_k=3, seed=8)
    assert len(c.survivors) == 3  # the count never depends on the seed

    # four candidates tie at the promotion boundary, so the seed decides which of them is promoted
    thirds = {
        screen_two_stage(list(range(6)), c_eval, f_eval, keep=3, top_k=3, seed=s).survivors[2] for s in range(10)
    }
    assert len(thirds) > 1, "the seed did not break the tie"


def test_the_report_serialises_to_json():
    c_eval, f_eval = _fake_tiers([3, 2, 1], [1, 2, 3])
    report = screen_two_stage(list(range(3)), c_eval, f_eval, keep=2, top_k=2, seed=0)
    text = json.dumps(report.to_dict())
    assert "spearman_coarse_vs_fine" in text
    assert json.loads(text)["n_candidates"] == 3


# ---------------------------------------------------------------------------------------
# the coarse tier itself (kinematics only, no physics)
# ---------------------------------------------------------------------------------------
def test_the_coarse_metrics_reproduce_the_v04_formulas():
    design = design_variants(BASE, [("x", {})])[0]
    duty = coarse_kinematic_score(design, "duty")
    stroke = coarse_kinematic_score(design, "stroke")
    assert stroke > 0
    assert duty > 0
    # duty = min(duty,0.6) * (1+min(lift/width,0.4)) * (stroke/width) on the same 90 samples
    from strandbeest_common.gait import gait_metrics
    from strandbeest_common.linkage import load_spec

    m = gait_metrics(load_spec(design["linkage"]), 90)
    ratio = m.lift / max(m.width, 1e-4)
    expected = min(m.duty, 0.6) * (1.0 + min(ratio, 0.4)) * (m.stroke_length / max(m.width, 1e-4))
    assert abs(duty - expected) < 1e-12


def test_the_coarse_evaluator_rejects_an_unknown_metric():
    with pytest.raises(ValueError):
        make_coarse_evaluator("not-a-metric")({"linkage": BASE["linkage"]})


def test_the_coarse_tier_is_cheap_enough_to_be_a_filter():
    import time

    evaluate = make_coarse_evaluator("duty")
    designs = design_variants(BASE, [(f"d{i}", {"m": 15.0 + 0.1 * i}) for i in range(20)])
    t0 = time.perf_counter()
    for d in designs:
        evaluate(d)
    per_eval = (time.perf_counter() - t0) / len(designs)
    assert per_eval < 0.05  # 20 kinematic evaluations in well under a second


def test_the_module_does_not_import_the_simulator_at_module_level():
    """`strandbeest_opt` must stay importable (and testable) without `packages/sim`."""
    tree = ast.parse(Path(multifidelity.__file__).read_text())
    top_level_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    imported = set()
    for node in top_level_imports:
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        else:
            imported.add(node.module or "")
    assert not any(name.startswith("strandbeest_sim") for name in imported), imported


# ---------------------------------------------------------------------------------------
# the discard sweep
# ---------------------------------------------------------------------------------------
def test_the_discard_sweep_says_how_much_can_be_thrown_away():
    coarse = [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    fine = [12, 11, 10, 9, 7, 8, 6, 5, 4, 3, 2, 1]
    sweep = discard_sweep(coarse, fine, keeps=[5, 6, 7, 12], top_k=5, seed=1)
    assert [row["keep"] for row in sweep] == [5, 6, 7, 12]
    # keeping 5 of 12 is not enough here (the coarse tier's 5th is not the fine tier's 5th)
    assert sweep[0]["retained_count"] == 4
    assert sweep[0]["retains_all"] is False
    # keeping 6 of 12 catches all five
    assert sweep[1]["retained_count"] == 5
    assert sweep[1]["retains_all"] is True
    assert sweep[1]["discard_ratio"] == pytest.approx(0.5)
    # keeping all of them trivially catches all five
    assert sweep[3]["retained_count"] == 5
    assert sweep[3]["discard_ratio"] == 0.0


# ---------------------------------------------------------------------------------------
# the real two tiers (needs the simulator)
# ---------------------------------------------------------------------------------------
@pytest.mark.slow
def test_the_real_two_stage_screen_runs_and_the_fine_tier_is_the_expensive_one():
    designs = design_variants(BASE, [("d0", {}), ("d1", {"m": 13.0})])
    coarse = make_coarse_evaluator("duty")
    fine = make_fine_evaluator()

    report = screen_two_stage(designs, coarse, fine, keep=1, min_keep=1, top_k=1, seed=0)

    assert report.coarse_timing.n_evaluations == 2
    assert report.fine_timing.n_evaluations == 1
    assert report.fine_timing.seconds > report.coarse_timing.seconds  # the physics is the expensive tier
    assert math.isfinite(report.spearman)


def test_adaptive_screening_discards_bottom_quarter():
    from strandbeest_opt.multifidelity import adaptive_screening

    # 12 candidates, coarse scores [12..1], fine scores reversed
    coarse = list(range(12, 0, -1))
    fine = list(range(1, 13))
    c_eval, f_eval = _fake_tiers(coarse, fine)
    candidates = list(range(12))

    # Discard 25% (3 of 12), retaining top 9
    report = adaptive_screening(candidates, c_eval, f_eval, discard_fraction=0.25)
    assert report.n_candidates == 12
    assert len(report.survivors) == 9
    assert report.n_discarded == 3
    assert report.discard_ratio == pytest.approx(0.25)


def test_select_survivors_with_keep_and_discard_fractions():
    scores = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]  # 10 items
    # Discard 20% -> keep 8
    surv_d20, _ = select_survivors(scores, discard_fraction=0.2)
    assert len(surv_d20) == 8
    assert surv_d20 == list(range(8))

    # Keep 50% -> keep 5
    surv_k50, _ = select_survivors(scores, keep_fraction=0.5)
    assert len(surv_k50) == 5
    assert surv_k50 == list(range(5))

    with pytest.raises(ValueError, match="discard_fraction"):
        select_survivors(scores, discard_fraction=1.5)
    with pytest.raises(ValueError, match="keep_fraction"):
        select_survivors(scores, keep_fraction=0.0)

