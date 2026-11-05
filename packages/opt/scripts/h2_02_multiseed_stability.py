"""H2-02: Multi-seed optimization x dual-solver rank stability verification (docs/ACTIONS.md).

Pipeline:
1. Run evolutionary optimization across >= 10 random seeds (seeds 1..10) under the declared
   candidate parameter space (linkage and sail genes) and wind-driven scenario.
2. For each seed, select top candidate designs.
3. Re-evaluate every selected candidate design on BOTH physics backends:
   - MuJoCo (MujocoBackend)
   - K2 (K2Backend)
4. For each seed and pooled overall:
   - Calculate Spearman rank correlation rho_s.
   - Calculate Top-k overlap ratio and Jaccard index (k=5).
   - Record failure proportions (stalled / non-walking) for MuJoCo vs K2.
   - Calculate statistical uncertainty intervals (mean, std, 95% confidence intervals).
5. Gate against pre-declared acceptance thresholds:
   - Unstable rankings are NOT output as verified winners.

Writes experiments/hardening-h2-02-multiseed-dual-solver-2026-11-05.json
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/common/src"))
sys.path.insert(0, str(ROOT / "packages/sim/src"))
sys.path.insert(0, str(ROOT / "packages/opt/src"))

from strandbeest_common import Design  # noqa: E402
from strandbeest_common.linkage import load_spec, solve_pose  # noqa: E402
from strandbeest_opt.optimizers import CmaEs  # noqa: E402
from strandbeest_opt.sailgenes import GeneBound, SailSpace  # noqa: E402
from strandbeest_opt.stability import (  # noqa: E402
    MultiSeedStabilityResult,
    StabilityThresholds,
    analyze_multiseed_stability,
    spearman_rank_correlation,
    top_k_overlap,
)
from strandbeest_sim.backends.k2_backend import K2Backend  # noqa: E402
from strandbeest_sim.backends.mujoco_backend import MujocoBackend  # noqa: E402
from strandbeest_sim.from_design import scenario_from_design  # noqa: E402
from strandbeest_sim.runner import run  # noqa: E402

DESIGN_PATH = ROOT / "schemas/examples/design-jansen-small-6leg.json"
BASE_DESIGN = json.loads(DESIGN_PATH.read_text())

ASSEMBLY_PROBES = 24

LINK_GENES = (
    GeneBound(
        name="m",
        low=12.0,
        high=18.0,
        unit="length units (1 unit = 2 mm)",
        reference=float(BASE_DESIGN["linkage"]["params"]["m"]),
        assumption="assumption: crank length box [12, 18] around reference 15; declared box from O-07.",
    ),
    GeneBound(
        name="a",
        low=36.0,
        high=40.0,
        unit="length units (1 unit = 2 mm)",
        reference=float(BASE_DESIGN["linkage"]["params"]["a"]),
        assumption="assumption: hip offset box [36, 40] around reference 38; declared box from O-07.",
    ),
    GeneBound(
        name="h",
        low=60.0,
        high=70.0,
        unit="length units (1 unit = 2 mm)",
        reference=float(BASE_DESIGN["linkage"]["params"]["h"]),
        assumption="assumption: thigh length box [60, 70] around reference 65.7; declared box from O-07.",
    ),
)

SAIL_GENES = (
    GeneBound(
        name="sail_area_m2",
        low=0.010,
        high=0.080,
        unit="m2",
        reference=float(BASE_DESIGN["drive"]["sail"]["area_m2"]),
        assumption="assumption: sail panel area [0.010, 0.080] m2 around reference 0.030 m2; declared box from W-08.",
    ),
    GeneBound(
        name="sail_gear",
        low=4.0,
        high=24.0,
        unit="1 (sail turns per crank turn)",
        reference=float(BASE_DESIGN["drive"]["sail"]["gear"]),
        assumption="assumption: sail reduction gear ratio [4, 24] around reference 10; declared box from W-08.",
    ),
)


def get_space() -> SailSpace:
    return SailSpace(base_design=BASE_DESIGN, link_genes=LINK_GENES, sail_genes=SAIL_GENES)


def evaluate_simulation(
    doc: dict[str, Any],
    backend: Any,
    overrides: dict[str, Any],
) -> tuple[float, bool, dict[str, Any]]:
    """Evaluate one design under the given backend and scenario overrides.

    Returns:
        (score, failed, metrics)
    """
    spec = load_spec(doc["linkage"])
    if any(solve_pose(spec, 2 * math.pi * i / ASSEMBLY_PROBES) is None for i in range(ASSEMBLY_PROBES)):
        return -1.0, True, {"assembly_failed": True}

    sc = scenario_from_design(Design(copy.deepcopy(doc)), overrides)
    try:
        res = run(sc, backend=backend)
        failed = bool(res.stalled or len(res.x) < 2)
        dist = float(res.x[-1] - res.x[0]) if not failed else -1.0
        metrics = {
            "stalled": res.stalled,
            "distance_m": dist,
            "stride_per_rev": float(res.metrics.get("stride_per_rev", 0.0) or 0.0),
            "mean_speed": float(res.metrics.get("mean_speed", 0.0) or 0.0),
            "max_loop_violation": float(res.metrics.get("max_loop_violation", 0.0) or 0.0),
        }
        return dist, failed, metrics
    except Exception as exc:
        return -1.0, True, {"solver_exception": str(exc)}


def run_single_seed_optimization(
    seed: int,
    space: SailSpace,
    mj_backend: MujocoBackend,
    k2_backend: K2Backend,
    overrides: dict[str, Any],
    popsize: int = 8,
    generations: int = 5,
    top_n: int = 10,
    top_k: int = 5,
) -> dict[str, Any]:
    """Execute CMA-ES on one seed and re-evaluate top candidates on both backends."""
    dim = space.dimension
    x0 = [0.5] * dim
    bounds = ([0.0] * dim, [1.0] * dim)
    opt = CmaEs(x0, sigma0=0.20, bounds=bounds, seed=seed, popsize=popsize)

    history: list[tuple[float, list[float]]] = []

    # Evolution loop
    for gen in range(generations):
        xs = opt.ask()
        scores = []
        for x in xs:
            g = space.from_unit(x)
            doc = space.to_design(g)
            score, failed, _ = evaluate_simulation(doc, mj_backend, overrides)
            scores.append(score)
            history.append((score, g))
        opt.tell(xs, scores)

    # Sort descending and pick top unique candidates
    history.sort(key=lambda t: t[0], reverse=True)
    top_candidates: list[list[float]] = []
    seen = set()
    for _, g in history:
        k = tuple(round(v, 4) for v in g)
        if k not in seen:
            seen.add(k)
            top_candidates.append(g)
        if len(top_candidates) == top_n:
            break

    # Dual-solver re-evaluation
    cand_details = []
    mj_scores: list[float] = []
    k2_scores: list[float] = []
    mj_failures: list[bool] = []
    k2_failures: list[bool] = []

    for rank_idx, g in enumerate(top_candidates):
        doc = space.to_design(g)
        score_mj, fail_mj, metrics_mj = evaluate_simulation(doc, mj_backend, overrides)
        score_k2, fail_k2, metrics_k2 = evaluate_simulation(doc, k2_backend, overrides)

        mj_scores.append(score_mj)
        k2_scores.append(score_k2)
        mj_failures.append(fail_mj)
        k2_failures.append(fail_k2)

        cand_details.append({
            "rank_in_seed": rank_idx + 1,
            "genome": [round(float(v), 5) for v in g],
            "params": {name: round(float(val), 5) for name, val in zip(space.names, g)},
            "mujoco": {"score": score_mj, "failed": fail_mj, "metrics": metrics_mj},
            "k2": {"score": score_k2, "failed": fail_k2, "metrics": metrics_k2},
        })

    rho = spearman_rank_correlation(mj_scores, k2_scores)
    jac, ov, top_mj_idx, top_k2_idx = top_k_overlap(mj_scores, k2_scores, k=top_k)

    return {
        "seed": seed,
        "evaluations_in_opt": opt.evals,
        "best_opt_fitness": opt.best_f,
        "n_candidates": len(top_candidates),
        "candidates": cand_details,
        "mujoco_scores": mj_scores,
        "k2_scores": k2_scores,
        "mujoco_failures": mj_failures,
        "k2_failures": k2_failures,
        "spearman_rho": rho,
        "top_k_overlap": ov,
        "top_k_jaccard": jac,
        "top_k_mujoco_indices": top_mj_idx,
        "top_k_k2_indices": top_k2_idx,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="H2-02 Multi-seed optimization x dual-solver rank stability")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(1, 11)), help="Random seeds (default: 1..10)")
    parser.add_argument("--popsize", type=int, default=8, help="CMA-ES population size (default: 8)")
    parser.add_argument("--generations", type=int, default=5, help="CMA-ES generations per seed (default: 5)")
    parser.add_argument("--top-n", type=int, default=10, help="Number of top candidates per seed (default: 10)")
    parser.add_argument("--top-k", type=int, default=5, help="k for top-k overlap metric (default: 5)")
    parser.add_argument("--wind-speed", type=float, default=3.0, help="Constant wind speed in m/s (default: 3.0)")
    parser.add_argument("--revolutions", type=float, default=0.3, help="Crank revolutions per eval (default: 0.3)")
    parser.add_argument("--min-spearman", type=float, default=0.70, help="Acceptance threshold for Spearman rho (default: 0.70)")
    parser.add_argument("--min-top-k", type=float, default=0.60, help="Acceptance threshold for Top-k overlap (default: 0.60)")
    parser.add_argument("--max-failure-rate", type=float, default=0.05, help="Acceptance threshold for max failure rate (default: 0.05)")
    parser.add_argument("--out", type=str, default="experiments/hardening-h2-02-multiseed-dual-solver-2026-11-05.json")
    args = parser.parse_args()

    thresholds = StabilityThresholds(
        min_spearman=args.min_spearman,
        min_top_k_overlap=args.min_top_k,
        max_failure_rate=args.max_failure_rate,
    )

    space = get_space()
    mj_backend = MujocoBackend()
    k2_backend = K2Backend()

    overrides = {
        "drive": {"kind": "sail"},
        "wind": {"kind": "constant", "speed": float(args.wind_speed), "params": {"yaw_deg": 0.0}},
        "run": {"revolutions": float(args.revolutions), "settle": 0.1, "frame_rate": 0},
        "solver": {"timestep": 0.001},
    }

    print("================================================================================")
    print("H2-02: Multi-seed optimization x Dual-solver Rank Stability Verification")
    print(f"Seeds: {args.seeds} (Total: {len(args.seeds)})")
    print(f"Gene Space: {list(space.names)} (Dim: {space.dimension})")
    print(f"Scenario: Wind {args.wind_speed} m/s, revs={args.revolutions}, dt=0.001s")
    print(f"Pre-declared Acceptance Thresholds: Spearman rho >= {thresholds.min_spearman:.2f}, "
          f"Top-{args.top_k} overlap >= {thresholds.min_top_k_overlap:.1%}, Max failure <= {thresholds.max_failure_rate:.1%}")
    print("================================================================================")

    t_start = time.time()
    seed_records = []

    for s in args.seeds:
        t0 = time.time()
        rec = run_single_seed_optimization(
            seed=s,
            space=space,
            mj_backend=mj_backend,
            k2_backend=k2_backend,
            overrides=overrides,
            popsize=args.popsize,
            generations=args.generations,
            top_n=args.top_n,
            top_k=args.top_k,
        )
        dt = time.time() - t0
        rec["time_s"] = dt
        seed_records.append(rec)
        mj_fails = sum(rec["mujoco_failures"])
        k2_fails = sum(rec["k2_failures"])
        print(f"Seed {s:2d} | rho={rec['spearman_rho']:+.4f} | top-{args.top_k} ov={rec['top_k_overlap']:>5.1%} "
              f"| Jaccard={rec['top_k_jaccard']:.3f} | fails(MuJoCo={mj_fails}, K2={k2_fails}) | {dt:5.2f}s")

    total_time = time.time() - t_start

    # Statistical Uncertainty & Acceptance Gating
    analysis = analyze_multiseed_stability(seed_records, thresholds=thresholds, top_k=args.top_k)

    print("\n--------------------------------------------------------------------------------")
    print("Multi-seed Uncertainty Intervals (Mean, Std, 95% Student-t CI):")
    print("--------------------------------------------------------------------------------")
    for metric_name, ci_data in analysis.uncertainty.items():
        print(f"  {metric_name:<24s}: Mean = {ci_data['mean']:>7.4f}, Std = {ci_data['std']:>7.4f}, "
              f"95% CI = [{ci_data['ci_95_lo']:>7.4f}, {ci_data['ci_95_hi']:>7.4f}]")

    print("\n--------------------------------------------------------------------------------")
    print(f"Pooled Overall Verification (N={len(args.seeds) * args.top_n} evaluations):")
    print(f"  Pooled Spearman rho       : {analysis.pooled_spearman:+.4f} (Threshold: >= {thresholds.min_spearman})")
    print(f"  Pooled Top-{args.top_k} Overlap      : {analysis.pooled_top_k_overlap:.1%} (Threshold: >= {thresholds.min_top_k_overlap:.1%})")
    print(f"  Pooled Top-{args.top_k} Jaccard      : {analysis.pooled_top_k_jaccard:.4f}")
    print(f"  Pooled MuJoCo Failure Rate: {analysis.pooled_mujoco_failure_rate:.1%}")
    print(f"  Pooled K2 Failure Rate    : {analysis.pooled_k2_failure_rate:.1%}")
    print(f"  Passed Seeds              : {analysis.passed_seeds} ({len(analysis.passed_seeds)}/{len(args.seeds)})")
    print(f"  Failed Seeds              : {analysis.failed_seeds} ({len(analysis.failed_seeds)}/{len(args.seeds)})")
    print(f"  Is Stable                 : {analysis.is_stable}")
    print(f"  Verified Winner Output    : {analysis.is_verified_winner}")
    print(f"  Verdict                   : {analysis.verdict}")
    print("--------------------------------------------------------------------------------")

    out_artifact = {
        "metadata": {
            "card_id": "H2-02",
            "title": "Multi-seed optimization x dual-solver rank stability verification",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_wall_clock_s": total_time,
            "solvers": ["mujoco", "k2"],
        },
        "predeclared_thresholds": {
            "min_spearman_rho": thresholds.min_spearman,
            "min_top_k_overlap": thresholds.min_top_k_overlap,
            "max_failure_rate": thresholds.max_failure_rate,
            "rule": "Unstable rankings failing pre-declared thresholds are NOT output as verified winners.",
        },
        "gene_space": space.to_dict(),
        "scenario": overrides,
        "parameters": {
            "seeds": args.seeds,
            "popsize": args.popsize,
            "generations": args.generations,
            "top_n_candidates_per_seed": args.top_n,
            "top_k": args.top_k,
        },
        "results": analysis.to_dict(),
        "verified_winners": [] if not analysis.is_verified_winner else [
            # Only populated if verified stable across solvers
            cand for s_rec in analysis.seed_results for cand in s_rec["candidates"] if s_rec["is_stable"]
        ],
    }

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_artifact, indent=2) + "\n")
    print(f"\nWrote full experiment artifact to: {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
