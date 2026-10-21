"""O-03: two-tier multi-fidelity screening (kinematic coarse filter -> dynamic re-evaluation) and the ranking
stability of the top five.

The V-04 study (docs/EXPERIMENTS.md section 33) measured that the pure kinematic score ranks designs badly against
the dynamics (rho_s = 0.2448 against MuJoCo stride) but still keeps 60-80 % of the top five. This script turns that
into a pipeline and measures what the pipeline is worth:

  * the Spearman rank correlation between the coarse ranking and the fine ranking,
  * the top-5 overlap between the two layers,
  * how many candidates the coarse filter can throw away while the fine tier still sees every one of the best five,
  * the wall-clock cost of each tier (a filter is only worth it if the cheap tier is genuinely cheap),
  * a pressure test: the same pipeline under another solver, another friction model, another foot friction, another
    time step and another tie-break seed.

The candidate set is the 12 design families of the V-04 study, so the numbers are directly comparable with section 33.

  python packages/opt/scripts/multifidelity_run.py [--seeds 3] [--keep 5] [--top-k 5] [--verify]
      -> experiments/multifidelity-ranking.json

Everything except the measured wall-clock is deterministic for a fixed seed: the JSON carries a `deterministic_digest`
over everything but the cost section, and `--verify` recomputes it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "common" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "sim" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "opt" / "src"))

from strandbeest_opt.multifidelity import (  # noqa: E402
    FineTierConfig,
    agreement,
    design_variants,
    discard_sweep,
    make_coarse_evaluator,
    make_fine_evaluator,
    retention_of_true_top_k,
    screen_two_stage,
    select_survivors,
)
from strandbeest_opt.stability import check_ranking_stability  # noqa: E402
from strandbeest_sim.contract import _example_design  # noqa: E402

# The 12 candidate design families of the V-04 study (scripts/study_ranking_stability.py). Kept identical so the
# numbers of this study can be compared with section 33 of docs/EXPERIMENTS.md.
PARAM_VARIANTS = [
    ("D00_baseline", {}),
    ("D01_long_stroke", {"h": 68.0, "i": 51.0}),
    ("D02_high_lift", {"e": 58.0, "d": 42.0}),
    ("D03_crank_15_8", {"m": 15.8}),
    ("D04_crank_13_0", {"m": 13.0}),
    ("D05_wide_hip", {"a": 39.5}),
    ("D06_narrow_hip", {"a": 37.2}),
    ("D07_high_crank", {"l": 9.0}),
    ("D08_deep_foot", {"h": 68.0, "g": 38.0}),
    ("D09_compact", {"c": 37.5, "k": 60.0}),
    ("D10_stretched", {"b": 42.5, "j": 51.0}),
    ("D11_asym", {"c": 40.5, "f": 40.5}),
]

# The fine tier: one dynamic run per candidate. The first four conditions mirror the V-04 conditions; the last two
# are the extra pressure axes of this study (foot friction, time step).
CONDITIONS: dict[str, FineTierConfig] = {
    "K2_Nominal": FineTierConfig(backend="k2", metric="stride_per_rev", overrides={"terrain": {"friction": 1.5}}),
    "MuJoCo_Nominal": FineTierConfig(
        backend="mujoco", metric="stride_per_rev", overrides={"terrain": {"friction": 1.5}}
    ),
    "K2_Low_Friction": FineTierConfig(backend="k2", metric="stride_per_rev", overrides={"terrain": {"friction": 0.5}}),
    "K2_High_Friction": FineTierConfig(
        backend="k2", metric="stride_per_rev", overrides={"terrain": {"friction": 2.5}}
    ),
    "K2_Low_Foot_Friction": FineTierConfig(
        backend="k2",
        metric="stride_per_rev",
        overrides={"terrain": {"friction": 1.5}, "walker": {"foot_friction": 0.3}},
    ),
    "K2_Half_Timestep": FineTierConfig(
        backend="k2", metric="stride_per_rev", timestep=0.00025, overrides={"terrain": {"friction": 1.5}}
    ),
}

NOMINAL = "K2_Nominal"


class Memo:
    """A fine evaluator that runs each candidate once and re-uses the score on a cache hit.

    The study needs the fine score of *every* candidate (the oracle: without it we do not know which candidates the
    true fine top five are). The screen itself only needs the survivors, so the survivors are re-used from the cache.
    The measured cost of the fine tier therefore comes from the oracle pass, and the screen cost is reported
    separately as the production cost (k fine runs).
    """

    def __init__(self, fn: Callable[[Any], float]) -> None:
        self.fn = fn
        self.cache: dict[int, float] = {}
        self.real_seconds = 0.0
        self.real_calls = 0

    def __call__(self, cand: Any) -> float:
        key = id(cand)
        if key not in self.cache:
            t0 = time.perf_counter()
            value = float(self.fn(cand))
            self.real_seconds += time.perf_counter() - t0
            self.real_calls += 1
            self.cache[key] = value
            return value
        return self.cache[key]

    @property
    def seconds_per_evaluation(self) -> float:
        return self.real_seconds / self.real_calls if self.real_calls else 0.0


def check_variants_drift() -> bool:
    """The candidate set must stay the V-04 one; a drift would make the numbers incomparable with section 33."""
    scripts = ROOT / "scripts"
    if not (scripts / "study_ranking_stability.py").exists():
        return False
    sys.path.insert(0, str(scripts))
    try:
        from study_ranking_stability import PARAM_VARIANTS as v04
    except Exception:  # noqa: BLE001 - the check is a guard, not a hard dependency
        return False
    if [tuple(x) for x in v04] != [tuple(x) for x in PARAM_VARIANTS]:
        raise SystemExit("the candidate set drifted from scripts/study_ranking_stability.py (V-04)")
    return True


def digest_of(payload: dict[str, Any]) -> str:
    """A stable hash of everything that must not change between two runs with the same input."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evaluate_all(evaluator: Callable[[Any], float], candidates: Sequence[Any]) -> tuple[list[float], float]:
    scores = []
    t0 = time.perf_counter()
    for cand in candidates:
        scores.append(float(evaluator(cand)))
    return scores, time.perf_counter() - t0


def analyse(args, conditions, designs, ids, coarse_scores, stroke_scores, fine) -> dict[str, Any]:
    """Everything that does not depend on the wall clock: the two rankings, their agreement, the screen and the
    retention of the true fine top five."""
    n = len(designs)
    coarse_name = f"Coarse_{args.coarse_metric.capitalize()}"
    score_series = {
        coarse_name: coarse_scores,
        "Coarse_Stroke": stroke_scores,
        **{name: fine[name] for name in conditions},
    }
    stability = check_ranking_stability(score_series, k=args.top_k)

    screens: dict[str, Any] = {}
    retention: dict[str, Any] = {}
    for name in conditions:
        cfg = conditions[name]
        per_seed: dict[str, Any] = {}
        for seed in range(1, args.seeds + 1):
            report = screen_two_stage(
                designs,
                make_coarse_evaluator(args.coarse_metric),
                lambda cand, _n=name: fine[_n][ids.index(cand["name"])],
                keep=args.keep,
                min_keep=args.min_keep,
                top_k=args.top_k,
                seed=seed,
                ids=ids,
            )
            per_seed[str(seed)] = {
                "survivors": [ids[i] for i in report.survivors],
                "fine_order": [ids[i] for i in report.fine_order],
                "spearman_coarse_vs_fine_over_survivors": report.spearman,
                f"top_{args.top_k}_overlap_layers": report.top_k_overlap,
                f"top_{args.top_k}_coarse": report.top_k_coarse,
                f"top_{args.top_k}_fine": report.top_k_fine,
                "n_discarded": report.n_discarded,
                "discard_ratio": report.discard_ratio,
                "notes": report.notes,
            }
            kept = retention_of_true_top_k(
                coarse_scores, fine[name], keep=args.keep, top_k=args.top_k, seed=seed, ids=ids
            )
            per_seed[str(seed)]["retention_of_true_top_k"] = kept
        screens[name] = {
            "condition": cfg.label(),
            "backend": cfg.backend,
            "metric": cfg.metric,
            "overrides": cfg.overrides,
            "timestep": cfg.timestep,
            "per_seed": per_seed,
        }
        retention[name] = discard_sweep(
            coarse_scores, fine[name], keeps=list(range(1, n + 1)), top_k=args.top_k, seed=1, ids=ids
        )

    # --- pressure test: how stable is the top five across the conditions? -------------
    nominal_top = sorted(range(n), key=lambda i: (-fine[NOMINAL][i], i))[: args.top_k]
    nominal_ids = [ids[i] for i in nominal_top]
    top5_stability: dict[str, Any] = {}
    for name in conditions:
        other = sorted(range(n), key=lambda i: (-fine[name][i], i))[: args.top_k]
        shared = len(set(nominal_top) & set(other))
        top5_stability[name] = {
            "top_k_ids": [ids[i] for i in other],
            "shared_with_nominal": shared,
            "stability_vs_nominal": shared / args.top_k,
            "spearman_vs_nominal": agreement(fine[NOMINAL], fine[name], top_k=args.top_k)["spearman"],
        }
    retentions = [
        screens[name]["per_seed"][str(seed)]["retention_of_true_top_k"]["retained_count"]
        for name in conditions
        for seed in range(1, args.seeds + 1)
    ]
    overlaps = [
        screens[name]["per_seed"][str(seed)][f"top_{args.top_k}_overlap_layers"]
        for name in conditions
        for seed in range(1, args.seeds + 1)
    ]
    # does the coarse filter even have ties at the promotion boundary? (the seed can only matter where there are ties)
    survivors_seed1, _ = select_survivors(coarse_scores, keep=args.keep, min_keep=args.min_keep, seed=1)
    boundary = coarse_scores[survivors_seed1[-1]]
    n_ties_at_boundary = sum(1 for s in coarse_scores if s == boundary)

    headline = {
        "coarse_metric": args.coarse_metric,
        "fine_metric": "stride_per_rev",
        "n_candidates": n,
        "keep": args.keep,
        "top_k": args.top_k,
        "coarse_fine_spearman_full_set": {
            name: round(stability.spearman_matrix[coarse_name][name], 4) for name in conditions
        },
        "top_k_overlap_full_set": {
            name: round(stability.top_k_overlap_matrix[coarse_name][name], 4) for name in conditions
        },
        "retained_true_top_k_min": min(retentions),
        "retained_true_top_k_max": max(retentions),
        "retained_true_top_k_mean": round(sum(retentions) / len(retentions), 3),
        "layer_overlap_min": round(min(overlaps), 4),
        "layer_overlap_max": round(max(overlaps), 4),
        "top5_stability_vs_nominal_min": round(min(v["stability_vs_nominal"] for v in top5_stability.values()), 4),
        "top5_stability_vs_nominal_max": round(max(v["stability_vs_nominal"] for v in top5_stability.values()), 4),
        "nominal_top5": nominal_ids,
        "coarse_ties_at_the_promotion_boundary": n_ties_at_boundary,
    }

    deterministic = {
        "study": "O-03 multi-fidelity screening (kinematic coarse filter -> dynamic re-evaluation)",
        "candidate_set": {
            "source": "the 12 design families of the V-04 study (scripts/study_ranking_stability.py)",
            "matches_v04": check_variants_drift(),
            "ids": ids,
            "params": [dict(ov) for _, ov in PARAM_VARIANTS],
        },
        "coarse": {
            "metric": args.coarse_metric,
            "scores": dict(zip(ids, coarse_scores)),
            "stroke_scores": dict(zip(ids, stroke_scores)),
        },
        "fine": {name: dict(zip(ids, fine[name])) for name in conditions},
        "conditions": {name: cfg.label() for name, cfg in conditions.items()},
        "spearman_matrix": stability.spearman_matrix,
        "top_k_overlap_matrix": stability.top_k_overlap_matrix,
        "screens": screens,
        "retention_sweep": retention,
        "top5_stability": top5_stability,
        "headline": headline,
        "seeds": list(range(1, args.seeds + 1)),
        "min_keep": args.min_keep,
    }
    return {"deterministic": deterministic, "screens": screens, "top5_stability": top5_stability, "headline": headline}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=3, help="tie-break seeds of the coarse filter (default 3)")
    ap.add_argument("--keep", type=int, default=5, help="candidates the coarse tier promotes to the fine tier")
    ap.add_argument(
        "--min-keep", type=int, default=1, help="floor on the survivors, so a broken filter still returns something"
    )
    ap.add_argument("--top-k", type=int, default=5, help="size of the top set the numbers are reported for")
    ap.add_argument("--coarse-metric", default="duty", help="coarse metric: duty | stroke | flat_stroke | high_step")
    ap.add_argument(
        "--conditions", default="all", help="comma-separated subset of the fine-tier conditions (default: all)"
    )
    ap.add_argument("--out", default="experiments/multifidelity-ranking.json")
    ap.add_argument("--verify", action="store_true", help="recompute the analysis and check the deterministic digest")
    args = ap.parse_args(argv)

    drifted = check_variants_drift()
    conditions = (
        CONDITIONS
        if args.conditions == "all"
        else {name: CONDITIONS[name] for name in args.conditions.split(",") if name in CONDITIONS}
    )
    if not conditions:
        raise SystemExit(f"no known condition in '{args.conditions}'")

    ids = [name for name, _ in PARAM_VARIANTS]
    designs = design_variants(_example_design(), PARAM_VARIANTS)
    n = len(designs)
    print(f"=== O-03 multi-fidelity screening: {n} candidates, {len(conditions)} fine conditions ===")

    # --- coarse tier ------------------------------------------------------------------
    coarse_scores, coarse_seconds = evaluate_all(make_coarse_evaluator(args.coarse_metric), designs)
    stroke_scores, stroke_seconds = evaluate_all(make_coarse_evaluator("stroke"), designs)
    coarse_eps = n / coarse_seconds if coarse_seconds > 0 else float("inf")
    print(f"coarse tier ({args.coarse_metric}): {n} evals in {coarse_seconds:.4f} s ({coarse_eps:.1f} evals/s)")

    # --- fine tier: the oracle pass (every candidate, every condition) ----------------
    fine: dict[str, list[float]] = {}
    fine_seconds: dict[str, float] = {}
    for name, cfg in conditions.items():
        memo = Memo(make_fine_evaluator(cfg))
        scores, seconds = evaluate_all(memo, designs)
        fine[name] = scores
        fine_seconds[name] = seconds
        eps = n / seconds if seconds else float("inf")
        print(f"fine tier {name}: {n} evals in {seconds:.2f} s ({eps:.2f} evals/s)")

    result = analyse(args, conditions, designs, ids, coarse_scores, stroke_scores, fine)
    deterministic = result["deterministic"]
    screens = result["screens"]
    top5_stability = result["top5_stability"]
    headline = result["headline"]

    # --- cost model -------------------------------------------------------------------
    fine_per_condition = {
        name: {
            "n_evaluations": n,
            "seconds": round(fine_seconds[name], 4),
            "evaluations_per_second": round(n / fine_seconds[name], 3) if fine_seconds[name] else None,
            "seconds_per_evaluation": round(fine_seconds[name] / n, 6),
        }
        for name in conditions
    }
    t_coarse = coarse_seconds / n
    production = {
        name: {
            "screen_cost_seconds": round(n * t_coarse + args.keep * fine_seconds[name] / n, 4),
            "fine_only_cost_seconds": round(fine_seconds[name], 4),
            "speedup_vs_fine_only": round(
                fine_seconds[name] / (n * t_coarse + args.keep * fine_seconds[name] / n), 2
            ),
        }
        for name in conditions
    }

    payload = dict(deterministic)
    payload["costs"] = {
        "note": "wall-clock, machine dependent; excluded from the deterministic digest",
        "coarse": {
            "n_evaluations": n,
            "seconds": round(coarse_seconds, 6),
            "evaluations_per_second": round(coarse_eps, 3),
            "seconds_per_evaluation": round(t_coarse, 9),
            "stroke_metric_seconds": round(stroke_seconds, 6),
        },
        "fine_per_condition": fine_per_condition,
        "production_screen": production,
    }
    payload["deterministic_digest"] = digest_of(deterministic)

    out_path = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path.relative_to(ROOT)} (digest {payload['deterministic_digest'][:16]})")

    # --- the report, for the reader ----------------------------------------------------
    print("\n=== layer agreement (Spearman, over all 12 candidates) ===")
    for name in conditions:
        print(
            f"  {name:<22s} rho_s = {headline['coarse_fine_spearman_full_set'][name]:+.4f}   "
            f"top-{args.top_k} overlap = {headline['top_k_overlap_full_set'][name]:.1%}"
        )
    print(
        "\n=== the screen (keep = %d of %d, i.e. %.0f%% discarded) ==="
        % (args.keep, n, 100 * (1 - args.keep / n))
    )
    for name in conditions:
        row = screens[name]["per_seed"]["1"]
        kept = row["retention_of_true_top_k"]
        print(
            f"  {name:<22s} rho_s(survivors) = {row['spearman_coarse_vs_fine_over_survivors']:+.4f}   "
            f"layer top-{args.top_k} = {row[f'top_{args.top_k}_overlap_layers']:.1%}   "
            f"true top-{args.top_k} kept = {kept['retained_count']}/{args.top_k}"
        )
    print("\n=== pressure test: top-%d stability of the fine ranking ===" % args.top_k)
    for name, info in top5_stability.items():
        print(
            f"  {name:<22s} shared with {NOMINAL}: {info['shared_with_nominal']}/{args.top_k} "
            f"({info['stability_vs_nominal']:.0%})   rho_s vs nominal = {info['spearman_vs_nominal']:+.4f}"
        )
    print(
        f"\nretained true top-{args.top_k} over all conditions and seeds: "
        f"min {headline['retained_true_top_k_min']}, max {headline['retained_true_top_k_max']}, "
        f"mean {headline['retained_true_top_k_mean']}"
    )
    print(
        f"coarse ties at the promotion boundary: {headline['coarse_ties_at_the_promotion_boundary']} "
        f"(the seed can only matter where there are ties)"
    )
    print(
        f"\ncost: coarse {coarse_eps:.1f} evals/s, fine "
        + ", ".join(f"{name} {fine_per_condition[name]['evaluations_per_second']:.2f} evals/s" for name in conditions)
    )
    print(f"candidate set matches the V-04 study: {drifted}")

    if args.verify:
        again = analyse(args, conditions, designs, ids, coarse_scores, stroke_scores, fine)["deterministic"]
        ok = digest_of(again) == payload["deterministic_digest"]
        print(f"\ndeterminism check: {'PASS' if ok else 'FAIL'} (recomputed digest {digest_of(again)[:16]})")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
