"""W-08: the sail parameters become genes of the optimisation (docs/ACTIONS.md, card W-08).

The genome of `strandbeest_opt.space.GenomeSpace` is *the list of the named link lengths*, and the fitness corpus
(`contracts/fitness`) is checked against that definition, so this module does **not** widen it. Instead it adds a
sail gene space next to it:

- `SailSpace` declares which link lengths are searched, which sail fields are genes, and the **declared bounds** of
  every gene together with the assumption behind them (AGENTS.md: "every physical parameter that is a guess is a
  named config field with an assumption"). A genome of a `SailSpace` is `[link values..., sail values...]`.
  A space with **no** sail genes is the "fixed sail" space: the sail keeps the reference values.
- `SailObjective` combines the two things the card asks for into one scalar with an **explicit weighting**: the
  start wind (W-03 / W-05) and the gust robustness (the lower-tail CVaR of a scenario set, O-07). The two terms are
  normalised against the *reference design* under the same physics, so the score is a dimensionless relative
  improvement (0 = as good as the reference design).

Nothing here imports the simulator: the physics is injected (`evaluate(genome, scenario) -> forward distance` and
`start_wind(genome) -> m/s`), so the module is unit-testable with a fake landscape and the `opt` package keeps its
dependency list unchanged (no `strandbeest-sim`).
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .robust import DEFAULT_ALPHA, Scenario, cvar_lower

# The outcome of a scenario in which the design does not walk at all: the same convention as O-07
# (`robust_run.py`: a design that cannot be assembled counts as -1 m, far below any real distance).
DOES_NOT_WALK_M = -1.0

# The score of a candidate that cannot be evaluated at all (the linkage does not assemble, the solver crashed).
INFEASIBLE_SCORE = -1e9

# The clip of the two normalised terms. They are dimensionless ratios; the clip keeps one broken candidate from
# dominating the CMA-ES update.
START_TERM_CLIP = 2.0
ROBUST_TERM_CLIP = 3.0

# The injected physics. `evaluate` returns the forward distance in metres (higher is better); a non-finite value
# means "this candidate does not exist" (the linkage does not assemble). `start_wind` returns the start wind in m/s
# (+inf when the design never starts).
Evaluator = Callable[[Sequence[float], Scenario], float]
StartWindFn = Callable[[Sequence[float]], float]


@dataclass(frozen=True)
class GeneBound:
    """One gene: its declared range, its unit, the reference value and the assumption behind the range.

    `assumption` is mandatory: a range that is a guess must name why (AGENTS.md). The reference value must lie
    inside the range, otherwise the reference design itself would be outside the search box.
    """

    name: str
    low: float
    high: float
    unit: str
    assumption: str
    reference: float

    def __post_init__(self) -> None:
        if not self.assumption.strip():
            raise ValueError(f"gene '{self.name}' has no assumption; every guessed range must name one")
        if self.low > self.high:
            raise ValueError(f"gene '{self.name}': low > high")
        if not (self.low <= self.reference <= self.high):
            raise ValueError(
                f"gene '{self.name}': the reference value {self.reference} is outside [{self.low}, {self.high}]"
            )

    def clamp(self, value: float) -> float:
        """Clip a value into the declared range."""
        return max(float(self.low), min(float(self.high), float(value)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "low": float(self.low),
            "high": float(self.high),
            "unit": self.unit,
            "reference": float(self.reference),
            "assumption": self.assumption,
        }


@dataclass(frozen=True)
class SailParameters:
    """The two sail fields that become genes: the area of the sail and the sail-to-crank reduction ratio.

    The lever arm of the sail on its shaft (`radius_m`) is *not* a gene: it is a lever arm, not the size of the sail.
    """

    area_m2: float
    gear: float

    def to_dict(self) -> dict[str, Any]:
        return {"area_m2": float(self.area_m2), "gear": float(self.gear)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SailParameters":
        return cls(area_m2=float(data["area_m2"]), gear=float(data["gear"]))

    def to_overrides(self) -> dict[str, Any]:
        """The scenario overrides that set exactly these two fields of the drive."""
        return {"drive": {"sail_area": float(self.area_m2), "sail_gear": float(self.gear)}}

    @classmethod
    def from_overrides(
        cls,
        overrides: Mapping[str, Any] | None,
        *,
        default_area_m2: float = 0.03,
        default_gear: float = 10.0,
    ) -> "SailParameters":
        """The inverse of `to_overrides`: read the sail fields back out of a set of scenario overrides."""
        drive = dict((overrides or {}).get("drive") or {})
        return cls(
            area_m2=float(drive.get("sail_area", default_area_m2)),
            gear=float(drive.get("sail_gear", default_gear)),
        )


@dataclass(frozen=True)
class SailSpace:
    """A declared search space: some link lengths plus (optionally) the sail genes.

    `base_design` is the reference design document; `link_genes` are the link lengths that are searched (the other
    lengths of the design stay frozen at their reference values) and `sail_genes` are the sail fields that are genes.
    A space with no sail genes is the **fixed sail** space: `sail_of` then returns the reference sail.

    The genome is the concatenation `[link values..., sail values...]`; `to_unit` / `from_unit` map it affinely onto
    the unit cube so that a single CMA-ES sigma means the same thing for a 0.08 m² sail and a 70 mm link.
    """

    base_design: Mapping[str, Any]
    link_genes: tuple[GeneBound, ...]
    sail_genes: tuple[GeneBound, ...] = ()

    # ------------------------------------------------------------------ the gene vector
    @property
    def names(self) -> tuple[str, ...]:
        return tuple(g.name for g in self.link_genes) + tuple(g.name for g in self.sail_genes)

    @property
    def dimension(self) -> int:
        return len(self.link_genes) + len(self.sail_genes)

    @property
    def reference_genome(self) -> list[float]:
        return [g.reference for g in self.link_genes] + [g.reference for g in self.sail_genes]

    def bounds(self) -> tuple[list[float], list[float]]:
        """The declared box of the search (lower, upper), in the gene order."""
        genes = list(self.link_genes) + list(self.sail_genes)
        return [g.low for g in genes], [g.high for g in genes]

    def assumptions(self) -> dict[str, str]:
        """The assumption behind every gene, by name."""
        return {g.name: g.assumption for g in list(self.link_genes) + list(self.sail_genes)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "names": list(self.names),
            "dimension": self.dimension,
            "link_genes": [g.to_dict() for g in self.link_genes],
            "sail_genes": [g.to_dict() for g in self.sail_genes],
            "reference_genome": self.reference_genome,
            "fixed_sail": not self.sail_genes,
        }

    # ------------------------------------------------------------------ the mapping
    def link_values(self, genome: Sequence[float]) -> list[float]:
        """The link-length part of a genome."""
        values = list(map(float, genome))
        if len(values) < len(self.link_genes):
            raise ValueError(f"genome has {len(values)} values, expected at least {len(self.link_genes)}")
        return values[: len(self.link_genes)]

    def sail_values(self, genome: Sequence[float]) -> list[float]:
        """The sail-gene part of a genome (empty for a fixed-sail space)."""
        values = list(map(float, genome))
        if len(values) < self.dimension:
            raise ValueError(f"genome has {len(values)} values, expected {self.dimension}")
        return values[len(self.link_genes):]

    def reference_sail(self) -> SailParameters:
        """The sail of the reference design."""
        sail = dict((self.base_design.get("drive") or {}).get("sail") or {})
        return SailParameters(
            area_m2=float(sail.get("area_m2", 0.03)),
            gear=float(sail.get("gear", 10.0)),
        )

    def sail_of(self, genome: Sequence[float]) -> SailParameters:
        """The sail parameters a genome stands for (the reference sail for a fixed-sail space)."""
        values = self.sail_values(genome)
        if not values:
            return self.reference_sail()
        return SailParameters(area_m2=values[0], gear=values[1])

    def to_design(self, genome: Sequence[float]) -> dict[str, Any]:
        """The design document a genome stands for: the link lengths and the sail."""
        doc = copy.deepcopy(dict(self.base_design))
        params = dict(doc["linkage"]["params"])
        for gene, value in zip(self.link_genes, self.link_values(genome)):
            params[gene.name] = float(value)
        doc["linkage"]["params"] = params
        sail = self.sail_of(genome)
        drive = doc.setdefault("drive", {})
        block = dict(drive.get("sail") or {})
        block["area_m2"] = sail.area_m2
        block["gear"] = sail.gear
        drive["sail"] = block
        return doc

    def to_overrides(self, genome: Sequence[float]) -> dict[str, Any]:
        """The scenario overrides a genome stands for: which sail fields it sets."""
        return self.sail_of(genome).to_overrides()

    def from_overrides(self, overrides: Mapping[str, Any] | None) -> SailParameters:
        """The inverse of `to_overrides`."""
        reference = self.reference_sail()
        return SailParameters.from_overrides(
            overrides,
            default_area_m2=reference.area_m2,
            default_gear=reference.gear,
        )

    def genome_with_sail(self, link_values: Sequence[float], sail: SailParameters) -> list[float]:
        """The genome that stands for these link lengths and this sail."""
        values = [float(v) for v in link_values]
        if self.sail_genes:
            values += [float(sail.area_m2), float(sail.gear)]
        return values

    # ------------------------------------------------------------------ the bounds
    def validate(self, genome: Sequence[float]) -> list[float]:
        """Check a genome against the declared box; raise `ValueError` when it does not fit.

        This is the gate the objective uses: a candidate outside the box is *rejected*, not silently clipped.
        """
        values = list(map(float, genome))
        if len(values) != self.dimension:
            raise ValueError(f"genome has {len(values)} values, expected {self.dimension}")
        for gene, value in zip(list(self.link_genes) + list(self.sail_genes), values):
            if not (gene.low <= value <= gene.high):
                raise ValueError(
                    f"gene '{gene.name}' = {value} is outside its declared range [{gene.low}, {gene.high}]"
                )
        return values

    def clip(self, genome: Sequence[float]) -> list[float]:
        """A copy of the genome with every gene inside its declared range."""
        values = list(map(float, genome))
        if len(values) != self.dimension:
            raise ValueError(f"genome has {len(values)} values, expected {self.dimension}")
        genes = list(self.link_genes) + list(self.sail_genes)
        return [gene.clamp(value) for gene, value in zip(genes, values)]

    def to_unit(self, genome: Sequence[float]) -> list[float]:
        """Map a genome affinely onto the unit cube (0 = the low bound, 1 = the high bound)."""
        values = self.validate(genome)
        out = []
        for gene, value in zip(list(self.link_genes) + list(self.sail_genes), values):
            span = gene.high - gene.low
            out.append(0.5 if span <= 0 else (value - gene.low) / span)
        return out

    def from_unit(self, unit: Sequence[float]) -> list[float]:
        """The inverse of `to_unit`."""
        values = list(map(float, unit))
        if len(values) != self.dimension:
            raise ValueError(f"unit vector has {len(values)} values, expected {self.dimension}")
        out = []
        for gene, u in zip(list(self.link_genes) + list(self.sail_genes), values):
            out.append(gene.low + max(0.0, min(1.0, u)) * (gene.high - gene.low))
        return out

    # ------------------------------------------------------------------ the sampler
    def sample(self, rng: random.Random) -> list[float]:
        """Draw one genome from the declared box with the given seeded RNG."""
        out = []
        for gene in list(self.link_genes) + list(self.sail_genes):
            if gene.low == gene.high:
                out.append(float(gene.low))
            elif gene.unit in ("integer", "count"):
                out.append(float(rng.randint(int(gene.low), int(gene.high))))
            else:
                out.append(rng.uniform(float(gene.low), float(gene.high)))
        return out

    def sample_genomes(self, n: int, seed: int = 1) -> list[list[float]]:
        """Draw `n` genomes from the declared box with an explicit seed (no global RNG, AGENTS.md)."""
        if n < 0:
            raise ValueError("n must not be negative")
        rng = random.Random(int(seed))
        return [self.sample(rng) for _ in range(n)]


@dataclass(frozen=True)
class ObjectiveWeights:
    """The explicit weighting of the two terms of the objective.

    `start` weights the start-wind term and `robust` the gust-robustness term; they are non-negative and sum to 1,
    so the objective is a convex combination of two dimensionless terms. `robust = 0` is the **nominal** objective
    (the start wind alone) and `robust = 1` the **robust** objective (the gust robustness alone).
    """

    start: float = 0.5
    robust: float = 0.5

    def __post_init__(self) -> None:
        if self.start < 0.0 or self.robust < 0.0:
            raise ValueError(f"the weights must not be negative: start={self.start}, robust={self.robust}")
        if abs(self.start + self.robust - 1.0) > 1e-9:
            raise ValueError(
                f"the weights must sum to 1 (a convex combination), got start={self.start}, robust={self.robust}"
            )

    @classmethod
    def of_robust(cls, robust: float) -> "ObjectiveWeights":
        """The weighting with a given weight on the robustness term."""
        return cls(start=1.0 - float(robust), robust=float(robust))

    def to_dict(self) -> dict[str, float]:
        return {"start": float(self.start), "robust": float(self.robust)}


@dataclass(frozen=True)
class Anchors:
    """The three reference numbers the objective normalises against.

    All three come from the **reference design** (the reference linkage, the reference sail) evaluated with the same
    physics as the candidates: its start wind, its CVaR over the scenario set and its distance at the nominal
    scenario. The score is therefore a dimensionless relative improvement: 0 means "as good as the reference".
    """

    start_wind_m_s: float
    cvar_m: float
    distance_m: float

    def to_dict(self) -> dict[str, float]:
        return {
            "start_wind_m_s": float(self.start_wind_m_s),
            "cvar_m": float(self.cvar_m),
            "distance_m": float(self.distance_m),
        }


class SailObjective:
    """The objective of W-08: the start wind and the gust robustness in one number, with a stated weighting.

    - `evaluate(genome, scenario) -> forward distance` is the injected physics (higher is better).
    - `start_wind(genome) -> m/s` is the injected start-wind search (+inf when the design never starts).
    - `scenarios` is the declared scenario set; the robustness term is the lower-tail CVaR of the outcomes over it
      (`robust.cvar_lower`, the same estimator as O-07).

    The two terms are normalised against the `anchors` (the reference design):

        start_term  = clip(log(v_ref / v_start), -2, 2)          # a log ratio: the start wind scales as 1/sqrt(A*Cd)
        robust_term = clip((cvar - cvar_ref) / d_ref, -3, 3)     # metres of CVaR over metres of reference distance

    and the score is `weights.start * start_term + weights.robust * robust_term`.

    The weighting is a **design decision, not a fact**: raising the weight on the robustness term can make the start
    wind of the optimum worse, and the experiment reports what happens instead of hiding it behind one number.
    """

    def __init__(
        self,
        space: SailSpace,
        scenarios: Sequence[Scenario],
        evaluate: Evaluator,
        start_wind: StartWindFn,
        *,
        alpha: float = DEFAULT_ALPHA,
        weights: ObjectiveWeights | None = None,
        anchors: Anchors | None = None,
    ) -> None:
        self.space = space
        self.scenarios = list(scenarios)
        self.evaluate = evaluate
        self.start_wind = start_wind
        self.alpha = float(alpha)
        self.weights = weights or ObjectiveWeights()
        self.anchors = anchors
        self.scenario_evaluations = 0
        self.start_wind_evaluations = 0

    # ------------------------------------------------------------------ the pieces
    def outcomes(self, genome: Sequence[float]) -> list[float]:
        """The outcome of the design in every scenario of the set, in the order of the set."""
        batch = getattr(self.evaluate, "evaluate_batch", None)
        if batch is not None:
            values = [float(v) for v in batch(genome, self.scenarios)]
            self.scenario_evaluations += len(values)
            return values
        values = []
        for scenario in self.scenarios:
            self.scenario_evaluations += 1
            values.append(float(self.evaluate(genome, scenario)))
        return values

    def cvar_of(self, outcomes: Sequence[float]) -> float:
        """The lower-tail CVaR of the outcomes (the mean of the worst `alpha` fraction)."""
        if not outcomes:
            raise ValueError("the scenario set is empty")
        return cvar_lower(list(outcomes), self.alpha)

    def start_wind_value(self, genome: Sequence[float]) -> float:
        """The start wind of the design (m/s); +inf when it never starts."""
        self.start_wind_evaluations += 1
        return float(self.start_wind(genome))

    def start_term(self, start_wind_m_s: float) -> float:
        """The normalised start-wind term: positive means "starts in less wind than the reference design"."""
        if self.anchors is None:
            raise ValueError("the objective needs the anchors (the reference design) to normalise the terms")
        v_ref = float(self.anchors.start_wind_m_s)
        if not math.isfinite(start_wind_m_s) or start_wind_m_s <= 0.0:
            return -START_TERM_CLIP  # the design never starts
        value = math.log(v_ref / start_wind_m_s)
        return max(-START_TERM_CLIP, min(START_TERM_CLIP, value))

    def robust_term(self, cvar_m: float) -> float:
        """The normalised robustness term: positive means "a better gust robustness than the reference design"."""
        if self.anchors is None:
            raise ValueError("the objective needs the anchors (the reference design) to normalise the terms")
        d_ref = float(self.anchors.distance_m)
        if not math.isfinite(cvar_m):
            return -ROBUST_TERM_CLIP
        if d_ref <= 0.0:
            raise ValueError(f"the reference distance must be positive, got {d_ref}")
        value = (float(cvar_m) - float(self.anchors.cvar_m)) / d_ref
        return max(-ROBUST_TERM_CLIP, min(ROBUST_TERM_CLIP, value))

    # ------------------------------------------------------------------ the score
    def score_from_parts(self, start_wind_m_s: float, outcomes: Sequence[float]) -> float:
        """The score from already computed pieces (the experiment evaluates a population in parallel)."""
        if any(not math.isfinite(float(v)) for v in outcomes):
            return INFEASIBLE_SCORE  # the candidate does not exist (the linkage does not assemble)
        cvar = self.cvar_of(outcomes)
        return (
            self.weights.start * self.start_term(start_wind_m_s)
            + self.weights.robust * self.robust_term(cvar)
        )

    def score(self, genome: Sequence[float]) -> float:
        """The score of a genome: the start wind and the CVaR, combined with the stated weighting."""
        self.space.validate(genome)
        try:
            start_wind_m_s = self.start_wind_value(genome)
            outcomes = self.outcomes(genome)
        except Exception:
            return INFEASIBLE_SCORE  # a solver crash is a candidate that does not walk, not a crash of the experiment
        return self.score_from_parts(start_wind_m_s, outcomes)

    def report(self, genome: Sequence[float]) -> dict[str, Any]:
        """Everything the write-up needs about one candidate: the score, its two terms and the raw numbers."""
        start_wind_m_s = self.start_wind_value(genome)
        outcomes = self.outcomes(genome)
        cvar = self.cvar_of(outcomes)
        return {
            "genome": [float(v) for v in genome],
            "start_wind_m_s": float(start_wind_m_s),
            "cvar_m": float(cvar),
            "worst_case_m": float(min(outcomes)) if outcomes else float("nan"),
            "mean_m": float(sum(outcomes) / len(outcomes)) if outcomes else float("nan"),
            "start_term": self.start_term(start_wind_m_s),
            "robust_term": self.robust_term(cvar),
            "score": self.score_from_parts(start_wind_m_s, outcomes),
            "scenario_values": {sc.describe(): float(v) for sc, v in zip(self.scenarios, outcomes)},
        }
