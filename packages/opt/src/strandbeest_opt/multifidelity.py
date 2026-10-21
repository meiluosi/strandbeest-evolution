"""Two-tier multi-fidelity screening: cheap kinematics in front of expensive dynamics (O-03).

The V-04 study (docs/EXPERIMENTS.md section 33) measured how much of the *dynamic* ranking the pure kinematic score
reproduces: rho_s = 0.2448 against MuJoCo stride and 0.4685 against K2 stride, while still keeping 60-80 % of the
top five. The conclusion there was explicit: the kinematic score is a **filter**, not a **ranking** - good enough to
throw away hopeless geometries, not good enough to declare a winner. This module turns that observation into a
pipeline:

    coarse tier   kinematics only. Gait metrics of the foot path (stride length, lift, flat-stroke duty), no multibody
                  physics at all. Microseconds per candidate.
    fine tier     one dynamic run per survivor (K2 or MuJoCo). Milliseconds to seconds per candidate.

    report = screen_two_stage(candidates, coarse_eval, fine_eval, keep=5)

The pipeline scores every candidate coarsely, promotes the top `keep` of them, re-evaluates the survivors in the fine
tier, and returns **both** rankings plus their agreement. `min_keep` is a floor on the number of survivors, so a
broken or degenerate coarse filter can never silently return nothing. Ties in the coarse score are broken by a seeded
tie-break, so the selection is reproducible for a fixed seed and different seeds give a different (but equally
reproducible) promotion of tied candidates.

`packages/sim` is imported lazily inside the fine tier, so `strandbeest_opt` still imports and tests on its own
(same pattern as `stability.evaluate_stability_suite`).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from strandbeest_common.gait import gait_metrics
from strandbeest_common.linkage import load_spec

from .fitness import fitness_flat_stroke, fitness_high_step
from .space import GenomeSpace
from .stability import spearman_rank_correlation, top_k_overlap

COARSE_SAMPLES = 90  # the sample count the V-04 study used, so the coarse scores are comparable with it
COARSE_METRICS = ("duty", "stroke", "flat_stroke", "high_step")

CoarseEvaluator = Callable[[Any], float]
FineEvaluator = Callable[[Any], float]


# --------------------------------------------------------------------------------------
# coarse tier: kinematics only
# --------------------------------------------------------------------------------------
def coarse_kinematic_score(design: dict[str, Any], metric: str = "duty") -> float:
    """Score one design from its kinematics alone (no multibody physics).

    Metrics:
        "duty"         the V-04 `Kinematic_Duty` score: min(duty, 0.6) * (1 + min(lift/width, 0.4)) * (stroke/width).
        "stroke"       the V-04 `Kinematic_Stroke` score: the x-span of the flat ground stroke.
        "flat_stroke"  the flat-stroke fitness of `fitness.py` (graded penalty for infeasible legs).
        "high_step"    the high-step fitness of `fitness.py` (lift/width, graded penalty for infeasible legs).

    "duty" and "stroke" reproduce the V-04 conditions exactly, so the numbers of this study can be compared with
    section 33 of docs/EXPERIMENTS.md without a re-baseline.
    """
    spec = load_spec(design["linkage"])
    if metric == "stroke":
        return float(gait_metrics(spec, COARSE_SAMPLES).stroke_length)
    if metric == "duty":
        m = gait_metrics(spec, COARSE_SAMPLES)
        ratio = m.lift / max(m.width, 1e-4)
        return float(min(m.duty, 0.6) * (1.0 + min(ratio, 0.4)) * (m.stroke_length / max(m.width, 1e-4)))
    if metric in ("flat_stroke", "high_step"):
        space = GenomeSpace.of(design["linkage"])
        genome = space.to_genome()
        fit = fitness_flat_stroke(space) if metric == "flat_stroke" else fitness_high_step(space)
        return float(fit(genome))
    raise ValueError(f"unknown coarse metric '{metric}', known: {COARSE_METRICS}")


def make_coarse_evaluator(metric: str = "duty") -> CoarseEvaluator:
    """A coarse evaluator over design dicts (kinematics only)."""

    def evaluate(design: dict[str, Any]) -> float:
        return coarse_kinematic_score(design, metric=metric)

    return evaluate


# --------------------------------------------------------------------------------------
# fine tier: one dynamic run per candidate
# --------------------------------------------------------------------------------------
@dataclass
class FineTierConfig:
    """How the fine tier runs the physics.

    backend      "k2" (independent planar rigid-body solver) or "mujoco".
    metric       the run metric to score, e.g. "stride_per_rev".
    revolutions  crank revolutions to drive (the V-04 study used 0.4).
    settle       seconds with the crank held before driving (the V-04 study used 0.2).
    timestep     the backend time step in s; None keeps the backend default. MuJoCo reads `solver.timestep`.
    overrides    extra scenario overrides, e.g. {"terrain": {"friction": 0.5}} or
                 {"walker": {"foot_friction": 0.3}}.
    """

    backend: str = "k2"
    metric: str = "stride_per_rev"
    revolutions: float = 0.4
    settle: float = 0.2
    timestep: float | None = None
    overrides: dict[str, Any] = field(default_factory=dict)

    def label(self) -> str:
        bits = [self.backend, self.metric]
        if self.timestep is not None:
            bits.append(f"dt={self.timestep:g}")
        for key, val in sorted(self.overrides.items()):
            if isinstance(val, dict):
                for k2, v2 in sorted(val.items()):
                    bits.append(f"{key}.{k2}={v2}")
            else:
                bits.append(f"{key}={val}")
        return ":".join(str(b) for b in bits)


def make_fine_evaluator(config: FineTierConfig | None = None) -> FineEvaluator:
    """A fine evaluator over design dicts: one dynamic run each.

    The `strandbeest_sim` import happens inside the closure, so importing this module does not pull in the simulator.
    """
    cfg = config or FineTierConfig()

    def evaluate(design: dict[str, Any]) -> float:
        from strandbeest_common import Design

        from strandbeest_sim.backends.k2_backend import K2Backend
        from strandbeest_sim.backends.mujoco_backend import MujocoBackend
        from strandbeest_sim.from_design import scenario_from_design
        from strandbeest_sim.runner import run

        overrides: dict[str, Any] = {
            "run": {
                "revolutions": cfg.revolutions,
                "settle": cfg.settle,
                "frame_rate": 0,  # no replay frames: we only want the metrics
                "max_time": 10.0,  # a guard; 0.4 revolutions at 2 rad/s never reaches it
            }
        }
        for key, val in cfg.overrides.items():
            if isinstance(val, dict):
                overrides.setdefault(key, {}).update(val)
            else:
                overrides[key] = val

        scenario = scenario_from_design(Design(design), overrides)
        if cfg.backend == "k2":
            backend = K2Backend(timestep=cfg.timestep) if cfg.timestep else K2Backend()
        elif cfg.backend == "mujoco":
            backend = MujocoBackend()
        else:
            raise ValueError(f"unknown fine-tier backend '{cfg.backend}', known: k2, mujoco")
        result = run(scenario, backend=backend)
        value = result.metrics.get(cfg.metric)
        return float(value) if value is not None else 0.0

    return evaluate


# --------------------------------------------------------------------------------------
# the pipeline
# --------------------------------------------------------------------------------------
@dataclass
class TierTiming:
    """What one tier cost."""

    n_evaluations: int = 0
    seconds: float = 0.0

    @property
    def evaluations_per_second(self) -> float:
        if self.seconds <= 0:
            return float("inf")
        return self.n_evaluations / self.seconds

    def to_dict(self) -> dict[str, Any]:
        eps = self.evaluations_per_second
        return {
            "n_evaluations": self.n_evaluations,
            "seconds": round(self.seconds, 6),
            "evaluations_per_second": (round(eps, 3) if math.isfinite(eps) else None),
            "seconds_per_evaluation": (round(self.seconds / self.n_evaluations, 9) if self.n_evaluations else None),
        }


@dataclass
class MultiFidelityReport:
    """The result of one two-stage screen: both rankings and how much they agree.

    fine_scores is indexed like candidate_ids; None marks a candidate the coarse tier discarded.
    """

    candidate_ids: list[str]
    coarse_scores: list[float]
    coarse_order: list[int]  # candidate indices, best coarse first
    survivors: list[int]  # candidate indices promoted to the fine tier, best coarse first
    fine_scores: list[float | None]
    fine_order: list[int]  # candidate indices, best fine first (survivors only)
    spearman: float  # coarse vs fine over the survivors
    top_k_overlap: float  # fraction of the top-k shared by the two layers
    top_k_jaccard: float
    top_k_coarse: list[str]
    top_k_fine: list[str]
    keep: int
    min_keep: int
    top_k: int
    coarse_timing: TierTiming
    fine_timing: TierTiming
    notes: list[str] = field(default_factory=list)

    @property
    def n_candidates(self) -> int:
        return len(self.candidate_ids)

    @property
    def n_discarded(self) -> int:
        return len(self.candidate_ids) - len(self.survivors)

    @property
    def discard_ratio(self) -> float:
        return self.n_discarded / self.n_candidates if self.candidate_ids else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_ids": self.candidate_ids,
            "coarse_scores": [None if math.isinf(s) else s for s in self.coarse_scores],
            "coarse_order": [self.candidate_ids[i] for i in self.coarse_order],
            "survivors": [self.candidate_ids[i] for i in self.survivors],
            "fine_scores": [None if s is None or math.isinf(s) else s for s in self.fine_scores],
            "fine_order": [self.candidate_ids[i] for i in self.fine_order],
            "spearman_coarse_vs_fine": self.spearman,
            f"top_{self.top_k}_overlap": self.top_k_overlap,
            f"top_{self.top_k}_jaccard": self.top_k_jaccard,
            f"top_{self.top_k}_coarse": self.top_k_coarse,
            f"top_{self.top_k}_fine": self.top_k_fine,
            "keep": self.keep,
            "min_keep": self.min_keep,
            "top_k": self.top_k,
            "n_candidates": self.n_candidates,
            "n_discarded": self.n_discarded,
            "discard_ratio": self.discard_ratio,
            "coarse_timing": self.coarse_timing.to_dict(),
            "fine_timing": self.fine_timing.to_dict(),
            "notes": list(self.notes),
        }

    def summary_table(self) -> str:
        lines = [
            f"Two-stage screen: {self.n_candidates} candidates, keep={self.keep} (floor {self.min_keep}), "
            f"top-{self.top_k}",
            f"  coarse tier : {self.coarse_timing.n_evaluations} evals in {self.coarse_timing.seconds:.4f} s "
            f"({self.coarse_timing.evaluations_per_second:.1f} evals/s)",
            f"  fine tier   : {self.fine_timing.n_evaluations} evals in {self.fine_timing.seconds:.4f} s "
            f"({self.fine_timing.evaluations_per_second:.3f} evals/s)",
            f"  discarded   : {self.n_discarded}/{self.n_candidates} ({self.discard_ratio:.1%})",
            f"  rho_s (coarse vs fine, over the survivors) = {self.spearman:.4f}",
            f"  top-{self.top_k} overlap = {self.top_k_overlap:.1%} (jaccard {self.top_k_jaccard:.1%})",
            f"  top-{self.top_k} coarse : {', '.join(self.top_k_coarse)}",
            f"  top-{self.top_k} fine   : {', '.join(self.top_k_fine)}",
        ]
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


def select_survivors(
    coarse_scores: Sequence[float], keep: int, min_keep: int = 1, seed: int = 0
) -> tuple[list[int], list[int]]:
    """Pick the candidates the coarse tier promotes: (survivors, full coarse order).

    The order is by descending coarse score; equal scores are broken by a seeded tie-break, so the selection is
    reproducible for a fixed seed. `min_keep` is a floor: even a degenerate (all-equal, all-failing) coarse filter
    promotes at least that many candidates, so the fine tier always has something to re-evaluate.
    """
    n = len(coarse_scores)
    if n == 0:
        return [], []
    if min_keep < 1:
        raise ValueError("min_keep must be >= 1")
    rng = random.Random(seed)
    tiebreak = [rng.random() for _ in range(n)]
    order = sorted(range(n), key=lambda i: (-coarse_scores[i], tiebreak[i]))
    n_keep = min(n, max(min_keep, min(keep, n)))
    return order[:n_keep], order


def screen_two_stage(
    candidates: Sequence[Any],
    coarse_evaluator: CoarseEvaluator,
    fine_evaluator: FineEvaluator,
    *,
    keep: int = 5,
    min_keep: int = 1,
    top_k: int = 5,
    seed: int = 0,
    ids: Sequence[str] | None = None,
) -> MultiFidelityReport:
    """Screen candidates coarsely, re-evaluate the survivors finely, and report both rankings.

    candidates   the things to screen (design dicts for the helpers above, anything for your own evaluators).
    keep         how many coarse survivors to promote to the fine tier.
    min_keep     floor on the number of survivors (a broken coarse filter still yields something).
    top_k        the size of the "top" set the agreement numbers are reported for.
    seed         the tie-break seed: a fixed seed gives a reproducible selection.

    A candidate whose evaluation raises is treated as the worst possible score (-inf) and reported in `notes`; it is
    never silently dropped.
    """
    n = len(candidates)
    if n == 0:
        raise ValueError("no candidates to screen")
    names = list(ids) if ids is not None else [f"c{i:03d}" for i in range(n)]
    if len(names) != n:
        raise ValueError(f"got {len(names)} ids for {n} candidates")
    notes: list[str] = []

    # --- coarse tier -----------------------------------------------------------------
    coarse_scores: list[float] = []
    coarse_failures = 0
    t0 = time.perf_counter()
    for i, cand in enumerate(candidates):
        try:
            score = float(coarse_evaluator(cand))
        except Exception as exc:  # noqa: BLE001 - a broken filter must not kill the screen
            coarse_failures += 1
            notes.append(f"coarse evaluation failed for {names[i]}: {type(exc).__name__}: {exc}")
            score = -math.inf
        if math.isnan(score):
            score = -math.inf
        coarse_scores.append(score)
    coarse_seconds = time.perf_counter() - t0
    if coarse_failures:
        notes.append(f"{coarse_failures}/{n} coarse evaluations failed and scored -inf")

    # --- promotion -------------------------------------------------------------------
    survivors, coarse_order = select_survivors(coarse_scores, keep=keep, min_keep=min_keep, seed=seed)
    if not survivors:  # unreachable with min_keep >= 1, but the floor must hold by construction
        notes.append("coarse filter produced no survivor; the min_keep floor kept the first candidate")
        survivors = [0]

    # --- fine tier -------------------------------------------------------------------
    fine_scores: list[float | None] = [None] * n
    fine_failures = 0
    t0 = time.perf_counter()
    for i in survivors:
        try:
            score = float(fine_evaluator(candidates[i]))
        except Exception as exc:  # noqa: BLE001
            fine_failures += 1
            notes.append(f"fine evaluation failed for {names[i]}: {type(exc).__name__}: {exc}")
            score = -math.inf
        if math.isnan(score):
            score = -math.inf
        fine_scores[i] = score
    fine_seconds = time.perf_counter() - t0
    if fine_failures:
        notes.append(f"{fine_failures}/{len(survivors)} fine evaluations failed and scored -inf")

    # --- agreement between the two layers --------------------------------------------
    coarse_surv = [coarse_scores[i] for i in survivors]
    fine_surv = [float(fine_scores[i]) for i in survivors]
    rng = random.Random(seed)
    tiebreak = [rng.random() for _ in range(n)]
    fine_order_local = sorted(range(len(survivors)), key=lambda j: (-fine_surv[j], tiebreak[survivors[j]]))
    fine_order = [survivors[j] for j in fine_order_local]
    rho = spearman_rank_correlation(coarse_surv, fine_surv)
    k_eff = min(top_k, len(survivors))
    jaccard, overlap, top_a, top_b = top_k_overlap(coarse_surv, fine_surv, k=k_eff)

    return MultiFidelityReport(
        candidate_ids=names,
        coarse_scores=coarse_scores,
        coarse_order=coarse_order,
        survivors=survivors,
        fine_scores=fine_scores,
        fine_order=fine_order,
        spearman=float(rho),
        top_k_overlap=float(overlap),
        top_k_jaccard=float(jaccard),
        top_k_coarse=[names[survivors[j]] for j in top_a],
        top_k_fine=[names[survivors[j]] for j in top_b],
        keep=keep,
        min_keep=min_keep,
        top_k=top_k,
        coarse_timing=TierTiming(n_evaluations=n, seconds=coarse_seconds),
        fine_timing=TierTiming(n_evaluations=len(survivors), seconds=fine_seconds),
        notes=notes,
    )


# --------------------------------------------------------------------------------------
# how much can the coarse filter throw away?
# --------------------------------------------------------------------------------------
def agreement(coarse_scores: Sequence[float], fine_scores: Sequence[float], top_k: int = 5) -> dict[str, Any]:
    """Spearman and top-k overlap between two complete score series over the same candidates."""
    if len(coarse_scores) != len(fine_scores):
        raise ValueError(f"score series differ in length: {len(coarse_scores)} vs {len(fine_scores)}")
    k_eff = min(top_k, len(coarse_scores))
    rho = spearman_rank_correlation(coarse_scores, fine_scores)
    jaccard, overlap, top_a, top_b = top_k_overlap(coarse_scores, fine_scores, k=k_eff)
    return {
        "spearman": float(rho),
        f"top_{k_eff}_overlap": float(overlap),
        f"top_{k_eff}_jaccard": float(jaccard),
        "top_coarse_indices": list(top_a),
        "top_fine_indices": list(top_b),
    }


def retention_of_true_top_k(
    coarse_scores: Sequence[float],
    fine_scores: Sequence[float],
    keep: int,
    top_k: int = 5,
    *,
    min_keep: int = 1,
    seed: int = 0,
    ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """How much of the *true* fine top-k the coarse filter keeps.

    This is the practically useful number of a screening pipeline: with the fine score of every candidate known (the
    oracle), how many candidates can the cheap tier throw away while the expensive tier still sees every one of the
    best `top_k` designs? Needs the fine score of all candidates, so it is a property of the *measurement*, not of a
    production run.
    """
    n = len(coarse_scores)
    if n != len(fine_scores):
        raise ValueError(f"score series differ in length: {n} vs {len(fine_scores)}")
    names = list(ids) if ids is not None else [f"c{i:03d}" for i in range(n)]
    survivors, _ = select_survivors(coarse_scores, keep=keep, min_keep=min_keep, seed=seed)
    kept = set(survivors)
    k_eff = min(top_k, n)
    order = sorted(range(n), key=lambda i: (-fine_scores[i], i))
    true_top = order[:k_eff]
    retained = [i for i in true_top if i in kept]
    missed = [i for i in true_top if i not in kept]
    return {
        "keep": keep,
        "min_keep": min_keep,
        "seed": seed,
        "top_k": k_eff,
        "n_candidates": n,
        "n_kept": len(survivors),
        "n_discarded": n - len(survivors),
        "discard_ratio": (n - len(survivors)) / n if n else 0.0,
        "true_top_k": [names[i] for i in true_top],
        "retained_count": len(retained),
        "retained": [names[i] for i in retained],
        "missed": [names[i] for i in missed],
        "retains_all": len(retained) == k_eff,
    }


def discard_sweep(
    coarse_scores: Sequence[float],
    fine_scores: Sequence[float],
    keeps: Sequence[int],
    top_k: int = 5,
    *,
    min_keep: int = 1,
    seed: int = 0,
    ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """`retention_of_true_top_k` for every requested `keep` value: the discard-ratio / retention curve."""
    return [
        retention_of_true_top_k(
            coarse_scores, fine_scores, keep=k, top_k=top_k, min_keep=min_keep, seed=seed, ids=ids
        )
        for k in keeps
    ]


def design_variants(base: dict[str, Any], variants: Sequence[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Copy a base design once per (name, parameter overrides) pair - the candidate set of a screening study."""
    import copy

    out: list[dict[str, Any]] = []
    for name, overrides in variants:
        design = copy.deepcopy(base)
        design["name"] = name
        design["linkage"]["params"].update(overrides)
        out.append(design)
    return out
