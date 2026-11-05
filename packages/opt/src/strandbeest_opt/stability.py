"""Design ranking stability analysis across physics backends, friction models, contact stiffness, and timesteps (V-04, O-03).

When optimisers, quality audits, or agent benchmarks compare candidate designs, the ranking must not flip wildly
under solver choice or contact regularization. If a candidate ranking changes drastically under physically plausible
model perturbations, the conclusions cannot be trusted without experimental elevation.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from strandbeest_common import Design


def rank_descending(scores: Sequence[float]) -> list[float]:
    """Assign fractional ranks in descending order (highest score gets rank 1.0). Handles ties by average rank."""
    n = len(scores)
    sorted_idx = sorted(range(n), key=lambda i: scores[i], reverse=True)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and scores[sorted_idx[j]] == scores[sorted_idx[i]]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[sorted_idx[k]] = avg_rank
        i = j
    return ranks


def spearman_rank_correlation(scores_a: Sequence[float], scores_b: Sequence[float]) -> float:
    """Calculate Spearman rank correlation rho_s between two evaluation series.

    Returns a value in [-1.0, 1.0], where 1.0 indicates identical relative order,
    0.0 indicates no monotonic association, and -1.0 indicates exact reversal.
    """
    if len(scores_a) != len(scores_b):
        raise ValueError(f"Arrays must have identical length, got {len(scores_a)} and {len(scores_b)}")
    if len(scores_a) < 2:
        return 1.0
    r_a = rank_descending(scores_a)
    r_b = rank_descending(scores_b)
    n = len(r_a)
    mean_a = sum(r_a) / n
    mean_b = sum(r_b) / n
    cov = sum((ra - mean_a) * (rb - mean_b) for ra, rb in zip(r_a, r_b))
    var_a = sum((ra - mean_a) ** 2 for ra in r_a)
    var_b = sum((rb - mean_b) ** 2 for rb in r_b)
    denom = math.sqrt(var_a * var_b)
    if denom < 1e-12:
        return 0.0
    return max(-1.0, min(1.0, cov / denom))


def top_k_overlap(
    scores_a: Sequence[float], scores_b: Sequence[float], k: int = 5
) -> tuple[float, float, list[int], list[int]]:
    """Compute Top-k agreement metrics between two score series.

    Returns:
        (jaccard, overlap_ratio, top_k_a_indices, top_k_b_indices)
    """
    n = len(scores_a)
    if len(scores_b) != n:
        raise ValueError(f"Arrays must have identical length, got {len(scores_a)} and {len(scores_b)}")
    k = min(k, n)
    top_a = sorted(range(n), key=lambda i: scores_a[i], reverse=True)[:k]
    top_b = sorted(range(n), key=lambda i: scores_b[i], reverse=True)[:k]
    intersection = len(set(top_a) & set(top_b))
    union = len(set(top_a) | set(top_b))
    jaccard = intersection / union if union > 0 else 1.0
    overlap_ratio = intersection / k if k > 0 else 1.0
    return jaccard, overlap_ratio, top_a, top_b


@dataclass
class RankingStabilityReport:
    """Quantitative report on ranking stability across an ensemble of conditions."""

    condition_names: list[str]
    n_designs: int
    top_k: int
    spearman_matrix: dict[str, dict[str, float]]
    top_k_jaccard_matrix: dict[str, dict[str, float]]
    top_k_overlap_matrix: dict[str, dict[str, float]]
    scores: dict[str, list[float]]
    stable_pairs: list[tuple[str, str, float, float]]
    unstable_pairs: list[tuple[str, str, float, float]]
    is_stable: bool
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_table(self) -> str:
        lines = []
        lines.append(f"Ranking Stability Analysis (N={self.n_designs} designs, Top-{self.top_k}):")
        lines.append(f"Overall Stability Verdict: {'STABLE (TRUSTWORTHY)' if self.is_stable else 'UNSTABLE (SENSITIVE)'}")
        lines.append("\nPairwise Spearman Rank Correlation Matrix:")
        header = f"{'Condition':<24s}" + "".join(f"{c[:10]:>12s}" for c in self.condition_names)
        lines.append(header)
        lines.append("-" * len(header))
        for c1 in self.condition_names:
            row = f"{c1:<24s}" + "".join(f"{self.spearman_matrix[c1][c2]:>12.4f}" for c2 in self.condition_names)
            lines.append(row)

        lines.append(f"\nTop-{self.top_k} Overlap Ratio Matrix (Fraction of top-{self.top_k} preserved):")
        lines.append(header)
        lines.append("-" * len(header))
        for c1 in self.condition_names:
            row = f"{c1:<24s}" + "".join(f"{self.top_k_overlap_matrix[c1][c2]:>12.1%}" for c2 in self.condition_names)
            lines.append(row)

        if self.stable_pairs:
            lines.append(f"\nStable Condition Pairs (rho >= 0.85, Top-{self.top_k} >= 60%):")
            for c1, c2, rho, top_ov in self.stable_pairs:
                lines.append(f"  - {c1} vs {c2}: rho = {rho:.4f}, Top-{self.top_k} overlap = {top_ov:.1%}")

        if self.unstable_pairs:
            lines.append(f"\nUnstable / Sensitive Condition Pairs (rho < 0.70 or Top-{self.top_k} < 40%):")
            for c1, c2, rho, top_ov in self.unstable_pairs:
                lines.append(f"  - {c1} vs {c2}: rho = {rho:.4f}, Top-{self.top_k} overlap = {top_ov:.1%}")

        return "\n".join(lines)


def check_ranking_stability(
    scores_by_condition: dict[str, Sequence[float]],
    k: int = 5,
    min_spearman: float = 0.80,
    min_top_k: float = 0.60,
) -> RankingStabilityReport:
    """Analyze ranking stability across precomputed scores from multiple conditions."""
    conditions = list(scores_by_condition)
    if not conditions:
        raise ValueError("scores_by_condition cannot be empty")
    n = len(scores_by_condition[conditions[0]])
    for c, sc in scores_by_condition.items():
        if len(sc) != n:
            raise ValueError(f"Condition '{c}' has {len(sc)} scores, expected {n}")

    k_eff = min(k, n)
    spearman_mat: dict[str, dict[str, float]] = {c1: {} for c1 in conditions}
    jaccard_mat: dict[str, dict[str, float]] = {c1: {} for c1 in conditions}
    overlap_mat: dict[str, dict[str, float]] = {c1: {} for c1 in conditions}

    stable_pairs = []
    unstable_pairs = []

    for i, c1 in enumerate(conditions):
        for j, c2 in enumerate(conditions):
            rho = spearman_rank_correlation(scores_by_condition[c1], scores_by_condition[c2])
            jac, ov, _, _ = top_k_overlap(scores_by_condition[c1], scores_by_condition[c2], k=k_eff)
            spearman_mat[c1][c2] = float(rho)
            jaccard_mat[c1][c2] = float(jac)
            overlap_mat[c1][c2] = float(ov)

            if i < j:
                if rho >= 0.85 and ov >= 0.60:
                    stable_pairs.append((c1, c2, rho, ov))
                if rho < 0.70 or ov < 0.40:
                    unstable_pairs.append((c1, c2, rho, ov))

    # Overall check: do solver cross-comparisons meet the thresholds?
    is_stable = len(unstable_pairs) == 0
    if is_stable:
        verdict = f"All {len(conditions)} conditions preserve design rankings (min rho >= 0.70, top-{k_eff} >= 40%)."
    else:
        unstable_desc = ", ".join(f"{c1}<->{c2}" for c1, c2, _, _ in unstable_pairs[:3])
        verdict = f"Ranking flips observed in {len(unstable_pairs)} condition pairs ({unstable_desc})."

    return RankingStabilityReport(
        condition_names=conditions,
        n_designs=n,
        top_k=k_eff,
        spearman_matrix=spearman_mat,
        top_k_jaccard_matrix=jaccard_mat,
        top_k_overlap_matrix=overlap_mat,
        scores={c: [float(s) for s in sc] for c, sc in scores_by_condition.items()},
        stable_pairs=stable_pairs,
        unstable_pairs=unstable_pairs,
        is_stable=is_stable,
        verdict=verdict,
    )


def evaluate_stability_suite(
    designs: Sequence[dict[str, Any] | Design],
    conditions: dict[str, dict[str, Any]],
    k: int = 5,
) -> RankingStabilityReport:
    """Run physics simulations and kinematic metrics across candidate designs and conditions, returning a full report.

    Each condition is a dictionary defining:
        - "backend": "k2" or "mujoco" or "kinematic"
        - "metric": "stride_per_rev" or "speed_mean" or "kinematic_flat_stroke" or "start_wind"
        - "overrides": scenario overrides (friction, timestep, stiffness, etc.)
    """
    from strandbeest_common.gait import gait_metrics
    from strandbeest_common.linkage import load_spec
    from strandbeest_sim.backends.k2_backend import K2Backend
    from strandbeest_sim.backends.mujoco_backend import MujocoBackend
    from strandbeest_sim.contract import _scenario
    from strandbeest_sim.dynamometer import virtual_dynamometer
    from strandbeest_sim.runner import run

    scores_by_cond: dict[str, list[float]] = {c: [] for c in conditions}

    # Normalize designs to dicts
    design_dicts = [d.doc if isinstance(d, Design) else d for d in designs]

    for d in design_dicts:
        des_obj = Design(d)
        spec = load_spec(d["linkage"])

        for c_name, c_cfg in conditions.items():
            b_name = c_cfg.get("backend", "k2")
            metric_name = c_cfg.get("metric", "stride_per_rev")
            overrides = c_cfg.get("overrides", {})

            if b_name == "kinematic":
                if metric_name == "kinematic_flat_stroke":
                    m = gait_metrics(spec, 90)
                    ratio = m.lift / max(m.width, 1e-4)
                    score = min(m.duty, 0.6) * (1.0 + min(ratio, 0.4)) * (m.stroke_length / max(m.width, 1e-4))
                elif metric_name == "stroke_length":
                    m = gait_metrics(spec, 90)
                    score = m.stroke_length
                else:
                    raise ValueError(f"Unknown kinematic metric {metric_name}")
            elif metric_name == "start_wind":
                # Compute minimum start wind using the virtual dynamometer
                dyn = virtual_dynamometer(des_obj, samples=60)
                # Lower start wind is better -> score as -start_wind or 1/start_wind
                score = -dyn["min_start_wind"]
            else:
                # Physics simulation
                backend_cls = K2Backend if b_name == "k2" else MujocoBackend
                base_ov = {"run": {"revolutions": 0.4, "settle": 0.2, "frame_rate": 0}}
                # Deep merge overrides
                merged_ov = copy.deepcopy(base_ov)
                for k_ov, v_ov in overrides.items():
                    if isinstance(v_ov, dict):
                        merged_ov.setdefault(k_ov, {}).update(v_ov)
                    else:
                        merged_ov[k_ov] = v_ov

                sc = _scenario(d, merged_ov)
                res = run(sc, backend=backend_cls())
                val = res.metrics.get(metric_name)
                score = float(val) if val is not None else 0.0

            scores_by_cond[c_name].append(score)

    return check_ranking_stability(scores_by_cond, k=k)


def confidence_interval(data: Sequence[float], confidence: float = 0.95) -> tuple[float, float, float, float]:
    """Calculate (mean, std, ci_lower, ci_upper) for a sample of values.

    Uses Student's t distribution when scipy is available, falling back to standard t-values.
    """
    n = len(data)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0
    if n == 1:
        v = float(data[0])
        return v, 0.0, v, v
    mean = sum(data) / n
    var = sum((x - mean) ** 2 for x in data) / (n - 1)
    std = math.sqrt(max(0.0, var))
    if std < 1e-12:
        return float(mean), 0.0, float(mean), float(mean)

    try:
        from scipy.stats import t

        t_crit = float(t.ppf((1.0 + confidence) / 2.0, df=n - 1))
    except ImportError:
        t_table = {
            1: 12.706,
            2: 4.303,
            3: 3.182,
            4: 2.776,
            5: 2.571,
            6: 2.447,
            7: 2.365,
            8: 2.306,
            9: 2.262,
            10: 2.228,
            15: 2.131,
            20: 2.086,
            30: 2.042,
        }
        df = n - 1
        t_crit = t_table.get(df, 1.96)

    margin = t_crit * (std / math.sqrt(n))
    return float(mean), float(std), float(mean - margin), float(mean + margin)


@dataclass(frozen=True)
class StabilityThresholds:
    """Pre-declared acceptance thresholds for cross-solver rank stability verification (H2-02)."""

    min_spearman: float = 0.70
    min_top_k_overlap: float = 0.60
    max_failure_rate: float = 0.05


@dataclass
class MultiSeedStabilityResult:
    """Aggregated results of multi-seed cross-solver rank stability verification."""

    seed_results: list[dict[str, Any]]
    uncertainty: dict[str, dict[str, float]]
    pooled_spearman: float
    pooled_top_k_overlap: float
    pooled_top_k_jaccard: float
    pooled_mujoco_failure_rate: float
    pooled_k2_failure_rate: float
    thresholds: StabilityThresholds
    passed_seeds: list[int]
    failed_seeds: list[int]
    is_stable: bool
    is_verified_winner: bool
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_results": self.seed_results,
            "uncertainty": self.uncertainty,
            "pooled_spearman": float(self.pooled_spearman),
            "pooled_top_k_overlap": float(self.pooled_top_k_overlap),
            "pooled_top_k_jaccard": float(self.pooled_top_k_jaccard),
            "pooled_mujoco_failure_rate": float(self.pooled_mujoco_failure_rate),
            "pooled_k2_failure_rate": float(self.pooled_k2_failure_rate),
            "thresholds": asdict(self.thresholds),
            "passed_seeds": self.passed_seeds,
            "failed_seeds": self.failed_seeds,
            "is_stable": self.is_stable,
            "is_verified_winner": self.is_verified_winner,
            "verdict": self.verdict,
        }


def analyze_multiseed_stability(
    seed_records: Sequence[dict[str, Any]],
    thresholds: StabilityThresholds | None = None,
    top_k: int = 5,
) -> MultiSeedStabilityResult:
    """Compute uncertainty intervals and apply pre-declared acceptance thresholds across seeds."""
    thresh = thresholds or StabilityThresholds()
    if not seed_records:
        raise ValueError("seed_records cannot be empty")

    passed_seeds: list[int] = []
    failed_seeds: list[int] = []

    rhos = []
    overlaps = []
    jaccards = []
    fail_rates_mj = []
    fail_rates_k2 = []

    all_scores_mj: list[float] = []
    all_scores_k2: list[float] = []
    total_runs_mj = 0
    total_runs_k2 = 0
    total_fails_mj = 0
    total_fails_k2 = 0

    processed_records = []

    for rec in seed_records:
        s = rec["seed"]
        s_mj = list(rec["mujoco_scores"])
        s_k2 = list(rec["k2_scores"])
        n_cands = len(s_mj)

        if "spearman_rho" in rec:
            rho = float(rec["spearman_rho"])
        else:
            rho = spearman_rank_correlation(s_mj, s_k2)

        if "top_k_overlap" in rec and "top_k_jaccard" in rec:
            ov = float(rec["top_k_overlap"])
            jac = float(rec["top_k_jaccard"])
        else:
            jac, ov, _, _ = top_k_overlap(s_mj, s_k2, k=min(top_k, n_cands))

        if "mujoco_failures" in rec:
            f_mj = rec["mujoco_failures"]
            n_fail_mj = sum(1 for x in f_mj if x) if isinstance(f_mj, list) else int(f_mj)
        else:
            n_fail_mj = sum(1 for v in s_mj if v <= 0.0)

        if "k2_failures" in rec:
            f_k2 = rec["k2_failures"]
            n_fail_k2 = sum(1 for x in f_k2 if x) if isinstance(f_k2, list) else int(f_k2)
        else:
            n_fail_k2 = sum(1 for v in s_k2 if v <= 0.0)

        mj_rate = n_fail_mj / n_cands if n_cands > 0 else 0.0
        k2_rate = n_fail_k2 / n_cands if n_cands > 0 else 0.0

        rhos.append(rho)
        overlaps.append(ov)
        jaccards.append(jac)
        fail_rates_mj.append(mj_rate)
        fail_rates_k2.append(k2_rate)

        all_scores_mj.extend(s_mj)
        all_scores_k2.extend(s_k2)
        total_runs_mj += n_cands
        total_runs_k2 += n_cands
        total_fails_mj += n_fail_mj
        total_fails_k2 += n_fail_k2

        passes_seed = (
            rho >= thresh.min_spearman
            and ov >= thresh.min_top_k_overlap
            and mj_rate <= thresh.max_failure_rate
            and k2_rate <= thresh.max_failure_rate
        )
        if passes_seed:
            passed_seeds.append(s)
        else:
            failed_seeds.append(s)

        out_rec = dict(rec)
        out_rec["spearman_rho"] = rho
        out_rec["top_k_overlap"] = ov
        out_rec["top_k_jaccard"] = jac
        out_rec["mujoco_failure_rate"] = mj_rate
        out_rec["k2_failure_rate"] = k2_rate
        out_rec["is_stable"] = passes_seed
        processed_records.append(out_rec)

    # Uncertainty calculations (mean, std, 95% CI)
    def _pack_ci(vals: Sequence[float]) -> dict[str, float]:
        m, s, lo, hi = confidence_interval(vals, confidence=0.95)
        return {"mean": m, "std": s, "ci_95_lo": lo, "ci_95_hi": hi}

    uncertainty = {
        "spearman_rho": _pack_ci(rhos),
        "top_k_overlap": _pack_ci(overlaps),
        "top_k_jaccard": _pack_ci(jaccards),
        "mujoco_failure_rate": _pack_ci(fail_rates_mj),
        "k2_failure_rate": _pack_ci(fail_rates_k2),
    }

    # Pooled calculations
    pooled_rho = spearman_rank_correlation(all_scores_mj, all_scores_k2)
    p_jac, p_ov, _, _ = top_k_overlap(all_scores_mj, all_scores_k2, k=min(top_k, len(all_scores_mj)))
    pooled_mj_rate = total_fails_mj / total_runs_mj if total_runs_mj > 0 else 0.0
    pooled_k2_rate = total_fails_k2 / total_runs_k2 if total_runs_k2 > 0 else 0.0

    pooled_passes = (
        pooled_rho >= thresh.min_spearman
        and p_ov >= thresh.min_top_k_overlap
        and pooled_mj_rate <= thresh.max_failure_rate
        and pooled_k2_rate <= thresh.max_failure_rate
    )

    # Overall stability requires pooled passes AND majority of seeds pass without severe flips
    seed_pass_fraction = len(passed_seeds) / len(seed_records)
    is_stable = pooled_passes and (seed_pass_fraction >= 0.80)
    is_verified_winner = is_stable

    if is_stable:
        verdict = (
            f"STABLE: Dual-solver rankings agree across {len(passed_seeds)}/{len(seed_records)} seeds "
            f"(pooled rho={pooled_rho:.4f} >= {thresh.min_spearman}, top-{top_k} overlap={p_ov:.1%} >= {thresh.min_top_k_overlap:.1%})."
        )
    else:
        reasons = []
        if pooled_rho < thresh.min_spearman:
            reasons.append(f"pooled Spearman rho {pooled_rho:.4f} < {thresh.min_spearman}")
        if p_ov < thresh.min_top_k_overlap:
            reasons.append(f"pooled top-{top_k} overlap {p_ov:.1%} < {thresh.min_top_k_overlap:.1%}")
        if len(failed_seeds) > 0:
            reasons.append(f"{len(failed_seeds)}/{len(seed_records)} seeds failed stability criteria")
        verdict = (
            f"UNSTABLE (REJECTED): Cross-solver ranking inconsistency detected ({'; '.join(reasons)}). "
            f"Candidates cannot be output as verified winners without experimental physical elevation."
        )

    return MultiSeedStabilityResult(
        seed_results=processed_records,
        uncertainty=uncertainty,
        pooled_spearman=pooled_rho,
        pooled_top_k_overlap=p_ov,
        pooled_top_k_jaccard=p_jac,
        pooled_mujoco_failure_rate=pooled_mj_rate,
        pooled_k2_failure_rate=pooled_k2_rate,
        thresholds=thresh,
        passed_seeds=passed_seeds,
        failed_seeds=failed_seeds,
        is_stable=is_stable,
        is_verified_winner=is_verified_winner,
        verdict=verdict,
    )
