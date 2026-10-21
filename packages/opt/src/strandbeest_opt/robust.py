"""Robust optimisation and adversarial scenario search (O-07).

Three reusable pieces, none of which needs MuJoCo:

- `cvar_lower`: the lower-tail CVaR (expected shortfall) of a sample, in closed form, with the sign convention spelled out.
- `ScenarioSpace` / `ScenarioSampler` / `adversarial_search`: a *declared, named* scenario space (every parameter is either
  measured or a named assumption), a seeded sampler over it, and a search for the scenario in which a given design does worst.
- `RobustObjective` / `robust_optimise`: the same ask/tell optimiser (CMA-ES from `optimizers.py`) driven against the nominal
  scenario, against the CVaR of the scenario set, and against the worst case of that set, so the three designs can be compared.

The physics sits behind an injectable callable -- `evaluate(genome, scenario) -> forward distance` (higher is better) -- so the
machinery is unit-testable with a fake landscape and reusable by other agents. Nothing here imports the simulator.

Every physical parameter is a named axis with an `assumption` string (AGENTS.md): the space refuses to be built without one.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from .optimizers import CmaEs, Optimizer, optimize

# The tail probability of WIND.md section 5 ("the mean of the worst 10 %").
DEFAULT_ALPHA = 0.1

# Axis names of the standard scenario space. A space may declare any subset; the missing ones fall back to the nominal.
AXIS_WIND_SPEED = "wind_speed_m_s"
AXIS_WIND_KIND = "wind_kind"
AXIS_GUST_AMPLITUDE = "gust_amplitude_m_s"
AXIS_GUST_PERIOD = "gust_period_s"
AXIS_TURB_INTENSITY = "turbulence_intensity"
AXIS_TURB_SEED = "turbulence_seed"
AXIS_YAW = "yaw_deg"
AXIS_TERRAIN_KIND = "terrain_kind"
AXIS_SLOPE = "slope_deg"
AXIS_FRICTION = "friction"
AXIS_BUMP_COUNT = "bump_count"
AXIS_BUMP_HEIGHT = "bump_max_height_m"
AXIS_BUMP_SEED = "bump_seed"

CONTINUOUS = "continuous"
CATEGORICAL = "categorical"
INTEGER = "integer"

# The evaluator returns the forward distance in metres; higher is better. The adversarial search *minimises* it.
Evaluator = Callable[[Sequence[float], "Scenario"], float]


class BatchEvaluator(Protocol):
    """An evaluator that can also run many scenarios at once.

    Optional: the machinery uses it when it is there (a simulator run is expensive, so the scenarios of one candidate are
    best run side by side), and falls back to the plain callable otherwise.
    """

    def __call__(self, genome: Sequence[float], scenario: "Scenario") -> float: ...

    def evaluate_batch(self, genome: Sequence[float], scenarios: Sequence["Scenario"]) -> Sequence[float]: ...


# ---------------------------------------------------------------------------------------------------------------------
# CVaR
# ---------------------------------------------------------------------------------------------------------------------


def cvar_lower(values: Sequence[float], alpha: float = DEFAULT_ALPHA) -> float:
    """Lower-tail CVaR (expected shortfall) of a discrete sample: the closed form of Rockafellar & Uryasev (2000).

    Definition
    ----------
    With `q_alpha` the alpha-quantile of the outcome X (`F(q_alpha) >= alpha`),

        CVaR_alpha(X) = E[X | X <= q_alpha]
                      = q_alpha - (1/alpha) * E[(q_alpha - X)^+]
                      = max_z { z - (1/alpha) * E[(z - X)^+] }.

    For `n` samples sorted ascending `x_(1) <= ... <= x_(n)` and `m = alpha * n`, the Rockafellar-Uryasev programme has the
    closed-form solution

        CVaR_alpha = (1/m) * [ sum_{i=1..k} x_(i) + (m - k) * x_(k+1) ],     k = floor(m),

    i.e. the mean of the `k` smallest samples with a fractional weight `(m - k)` on the next one. When `alpha * n` is an
    integer this is exactly the "mean of the worst alpha fraction" estimator of WIND.md section 5; when `alpha * n < 1` the
    whole tail mass falls on the single smallest sample and the estimator degenerates to the sample minimum (this is a
    property of the discrete estimator, not a bug -- it is why the experiment states how many scenarios it sampled).

    Sign convention
    ---------------
    This is the lower tail *of the outcome itself*. The outcome here is the forward distance (higher is better), so
    `cvar_lower(distances)` is the mean of the worst outcomes and the robust optimiser **maximises** it. The upper-tail
    equivalent for a loss variable L is `-cvar_lower(-L)`.

    Parameters
    ----------
    values: the sample (outcomes). Must not be empty.
    alpha: tail probability in (0, 1]. `alpha = 1` returns the plain mean.
    """
    xs = sorted(float(v) for v in values)
    n = len(xs)
    if n == 0:
        raise ValueError("cvar_lower needs at least one value")
    if not 0.0 < alpha <= 1.0:
        raise ValueError(f"alpha must be in (0, 1], got {alpha}")
    m = alpha * n
    if m >= n:  # alpha == 1 (or a rounding artefact): the tail is the whole sample
        return sum(xs) / n
    k = int(math.floor(m))
    if k == 0:  # the tail mass is smaller than one sample: it sits entirely on the smallest one
        return xs[0]
    total = sum(xs[:k]) + (m - k) * xs[k]
    return total / m


def cvar_lower_empirical(values: Sequence[float], alpha: float = DEFAULT_ALPHA) -> float:
    """The plain "mean of the worst `round(alpha * n)` samples" estimator.

    Kept next to `cvar_lower` because WIND.md section 5 phrases the metric that way and because the two differ whenever
    `alpha * n` is not an integer: the closed form gives the (k+1)-th sample a fractional weight, this one drops it.
    """
    xs = sorted(float(v) for v in values)
    n = len(xs)
    if n == 0:
        raise ValueError("cvar_lower_empirical needs at least one value")
    if not 0.0 < alpha <= 1.0:
        raise ValueError(f"alpha must be in (0, 1], got {alpha}")
    k = max(1, int(round(alpha * n)))
    k = min(k, n)
    return sum(xs[:k]) / k


# ---------------------------------------------------------------------------------------------------------------------
# The scenario space
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Axis:
    """One declared axis of the scenario space.

    `assumption` is mandatory: a physical parameter that is a guess must be a named field with an assumption (AGENTS.md).
    """

    name: str
    kind: str
    assumption: str
    unit: str = ""
    low: float | None = None
    high: float | None = None
    values: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if not self.assumption.strip():
            raise ValueError(f"axis '{self.name}' has no assumption; every guessed parameter must name one")
        if self.kind not in (CONTINUOUS, CATEGORICAL, INTEGER):
            raise ValueError(f"axis '{self.name}': unknown kind '{self.kind}'")
        if self.kind == CATEGORICAL and not self.values:
            raise ValueError(f"axis '{self.name}' is categorical but declares no values")
        if self.kind in (CONTINUOUS, INTEGER) and (self.low is None or self.high is None):
            raise ValueError(f"axis '{self.name}' needs low and high")
        if self.kind in (CONTINUOUS, INTEGER) and self.low > self.high:
            raise ValueError(f"axis '{self.name}': low > high")

    def sample(self, rng: random.Random) -> Any:
        """Draw one value from this axis with the given seeded RNG."""
        if self.kind == CATEGORICAL:
            return self.values[rng.randrange(len(self.values))]
        if self.kind == INTEGER:
            return int(rng.randint(int(self.low), int(self.high)))
        return rng.uniform(float(self.low), float(self.high))

    def clamp(self, value: float) -> float:
        """Clip a continuous value into the declared bounds."""
        if self.kind == CATEGORICAL:
            raise TypeError(f"axis '{self.name}' is categorical; use its declared values")
        return max(float(self.low), min(float(self.high), float(value)))

    def step(self) -> float:
        """The initial refinement step of the adversarial search for this axis."""
        if self.kind == CATEGORICAL:
            return 0.0
        if self.kind == INTEGER:
            return max(1.0, round((float(self.high) - float(self.low)) / 4.0))
        return (float(self.high) - float(self.low)) / 4.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "kind": self.kind, "unit": self.unit, "assumption": self.assumption}
        if self.kind == CATEGORICAL:
            d["values"] = list(self.values)
        else:
            d["low"] = self.low
            d["high"] = self.high
        return d


@dataclass(frozen=True)
class Scenario:
    """One point of the scenario space: a named combination of wind, terrain and friction.

    `wind_params` / `terrain_params` hold the kind-specific parameters of the simulator's wind and terrain registries
    (`strandbeest_sim.winds`, `strandbeest_sim.terrains`); the scenario is translated into simulator overrides by
    `overrides()`.
    """

    wind_speed_m_s: float
    wind_kind: str = "constant"
    wind_params: Mapping[str, Any] = field(default_factory=dict)
    terrain_kind: str = "flat"
    terrain_params: Mapping[str, Any] = field(default_factory=dict)
    friction: float = 1.5
    slope_deg: float = 0.0
    label: str = ""

    def with_friction(self, friction: float) -> "Scenario":
        """The same scenario on a different ground friction (a sensitivity check: the label is regenerated)."""
        return Scenario(
            wind_speed_m_s=self.wind_speed_m_s,
            wind_kind=self.wind_kind,
            wind_params=dict(self.wind_params),
            terrain_kind=self.terrain_kind,
            terrain_params=dict(self.terrain_params),
            friction=float(friction),
            slope_deg=self.slope_deg,
            label=_label(
                self.wind_kind,
                self.wind_speed_m_s,
                float(self.wind_params.get("yaw_deg", 0.0)),
                self.terrain_kind,
                self.slope_deg,
                float(friction),
            ),
        )

    def overrides(self) -> dict[str, Any]:
        """The flat simulator scenario overrides this scenario stands for (no simulator import needed)."""
        return {
            "wind": {
                "kind": self.wind_kind,
                "speed": float(self.wind_speed_m_s),
                "params": dict(self.wind_params),
            },
            "terrain": {
                "kind": self.terrain_kind,
                "friction": float(self.friction),
                "slope_deg": float(self.slope_deg),
                "params": dict(self.terrain_params),
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "wind": {
                "kind": self.wind_kind,
                "speed_m_s": float(self.wind_speed_m_s),
                "params": dict(self.wind_params),
            },
            "terrain": {
                "kind": self.terrain_kind,
                "friction": float(self.friction),
                "slope_deg": float(self.slope_deg),
                "params": dict(self.terrain_params),
            },
        }

    def describe(self) -> str:
        if self.label:
            return self.label
        return (
            f"{self.wind_kind}@{self.wind_speed_m_s:.2f}m/s yaw={self.wind_params.get('yaw_deg', 0.0):.0f}deg "
            f"{self.terrain_kind} slope={self.slope_deg:.1f}deg mu={self.friction:.2f}"
        )


def _label(wind_kind: str, speed: float, yaw: float, terrain_kind: str, slope: float, friction: float) -> str:
    return (
        f"{wind_kind}@{speed:.2f}m/s yaw={yaw:.0f}deg / {terrain_kind} slope={slope:.1f}deg mu={friction:.2f}"
    )


def scenario_from_point(point: Mapping[str, Any], nominal: Scenario | None = None) -> Scenario:
    """Build a `Scenario` from a point of the scenario space.

    The wind and terrain parameters are assembled from the point according to the chosen kinds; a parameter that does not
    apply to the chosen kind is simply not passed on (for example `gusts` has no turbulence seed).
    """
    nominal = nominal or Scenario(wind_speed_m_s=0.0)

    def get(name: str, fallback: Any) -> Any:
        return point[name] if name in point else fallback

    wind_kind = str(get(AXIS_WIND_KIND, nominal.wind_kind))
    speed = float(get(AXIS_WIND_SPEED, nominal.wind_speed_m_s))
    yaw = float(get(AXIS_YAW, nominal.wind_params.get("yaw_deg", 0.0)))
    terrain_kind = str(get(AXIS_TERRAIN_KIND, nominal.terrain_kind))
    friction = float(get(AXIS_FRICTION, nominal.friction))
    slope = float(get(AXIS_SLOPE, nominal.slope_deg))

    wind_params: dict[str, Any] = {"yaw_deg": yaw}
    if wind_kind == "gusts":
        wind_params["amplitude"] = float(get(AXIS_GUST_AMPLITUDE, nominal.wind_params.get("amplitude", 1.0)))
        wind_params["period"] = float(get(AXIS_GUST_PERIOD, nominal.wind_params.get("period", 6.0)))
    elif wind_kind in ("turbulent", "profile_turbulent"):
        wind_params["intensity"] = float(get(AXIS_TURB_INTENSITY, nominal.wind_params.get("intensity", 0.15)))
        wind_params["seed"] = int(get(AXIS_TURB_SEED, nominal.wind_params.get("seed", 1)))
        wind_params["integral_length"] = float(nominal.wind_params.get("integral_length", 25.0))
        wind_params["dt"] = float(nominal.wind_params.get("dt", 0.05))
    elif wind_kind == "lull":
        wind_params["at"] = float(nominal.wind_params.get("at", 10.0))

    terrain_params: dict[str, Any] = {}
    if terrain_kind == "bumps":
        terrain_params["count"] = int(get(AXIS_BUMP_COUNT, nominal.terrain_params.get("count", 12)))
        terrain_params["max_height"] = float(get(AXIS_BUMP_HEIGHT, nominal.terrain_params.get("max_height", 0.015)))
        terrain_params["seed"] = int(get(AXIS_BUMP_SEED, nominal.terrain_params.get("seed", 1)))
    elif terrain_kind == "step":
        terrain_params.update(nominal.terrain_params)

    return Scenario(
        wind_speed_m_s=speed,
        wind_kind=wind_kind,
        wind_params=wind_params,
        terrain_kind=terrain_kind,
        terrain_params=terrain_params,
        friction=friction,
        slope_deg=slope,
        label=_label(wind_kind, speed, yaw, terrain_kind, slope, friction),
    )


@dataclass(frozen=True)
class ScenarioSpace:
    """A declared scenario space: named axes with their bounds and assumptions, plus the nominal scenario."""

    name: str
    axes: tuple[Axis, ...]
    nominal: Scenario
    notes: str = ""

    def axis(self, name: str) -> Axis:
        for a in self.axes:
            if a.name == name:
                return a
        raise KeyError(f"no axis '{name}' in space '{self.name}'")

    def has(self, name: str) -> bool:
        return any(a.name == name for a in self.axes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "notes": self.notes,
            "axes": [a.to_dict() for a in self.axes],
            "nominal": self.nominal.to_dict(),
        }


class ScenarioSampler:
    """A seeded sampler over a declared scenario space.

    Every draw comes from an explicit `random.Random(seed)` instance: there is no bare global RNG anywhere (AGENTS.md).
    The same seed and the same space give the same sequence of scenarios.
    """

    def __init__(self, space: ScenarioSpace, seed: int = 1) -> None:
        self.space = space
        self.seed = int(seed)
        self._rng = random.Random(self.seed)

    def sample_point(self) -> dict[str, Any]:
        """Draw one point of the space (one value per axis)."""
        return {a.name: a.sample(self._rng) for a in self.space.axes}

    def scenario_from_point(self, point: Mapping[str, Any]) -> Scenario:
        return scenario_from_point(point, self.space.nominal)

    def sample(self, n: int) -> list[Scenario]:
        """Draw `n` scenarios."""
        if n < 0:
            raise ValueError("n must not be negative")
        return [self.scenario_from_point(self.sample_point()) for _ in range(n)]

    def nominal(self) -> Scenario:
        """The declared nominal scenario of the space (not a draw)."""
        return self.space.nominal


# ---------------------------------------------------------------------------------------------------------------------
# Adversarial scenario search
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class AdversarialResult:
    """What the adversarial search found for one design."""

    scenario: Scenario
    value: float  # the evaluated quantity at the worst scenario (lowest found)
    evaluations: int
    random_value: float  # the worst value the random pool alone had found
    history: list[tuple[Scenario, float]] = field(default_factory=list)

    @property
    def improved(self) -> bool:
        """True when the local refinement beat the random pool."""
        return self.value < self.random_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.to_dict(),
            "value": self.value,
            "random_pool_value": self.random_value,
            "evaluations": self.evaluations,
            "refinement_improved": self.improved,
        }


def _neighbours(space: ScenarioSpace, point: Mapping[str, Any], step_scale: float) -> list[dict[str, Any]]:
    """One compass-search ring around `point`: +/- step on the continuous axes, the other categories on the categorical ones."""
    out: list[dict[str, Any]] = []
    for a in space.axes:
        if a.kind == CATEGORICAL:
            for v in a.values:
                if v != point.get(a.name):
                    p = dict(point)
                    p[a.name] = v
                    out.append(p)
        elif a.kind == INTEGER:
            s = max(1.0, a.step() * step_scale)
            for d in (-s, s):
                p = dict(point)
                p[a.name] = int(max(a.low, min(a.high, point.get(a.name, a.low) + d)))
                if p[a.name] != point.get(a.name):
                    out.append(p)
        else:
            s = a.step() * step_scale
            for d in (-s, s):
                p = dict(point)
                p[a.name] = a.clamp(point.get(a.name, a.low) + d)
                if p[a.name] != point.get(a.name):
                    out.append(p)
    return out


def adversarial_search(
    space: ScenarioSpace,
    design: Sequence[float],
    evaluate: Evaluator,
    *,
    seed: int = 1,
    n_random: int = 24,
    n_refine: int = 60,
    min_step_scale: float = 1.0 / 64.0,
) -> AdversarialResult:
    """Search the scenario space for the scenario in which the evaluated quantity is smallest.

    Two stages: a seeded random pool over the whole space (the "coarse" stage), then a compass / pattern search around the
    worst member of that pool (the "fine" stage) with a shrinking step. The search **minimises** the evaluated quantity: with
    the forward-distance convention that means it looks for the scenario where the walker does worst.

    `design` is the design under test and `evaluate(design, scenario) -> forward distance` is the injected physics, so the
    search can be tested without any simulator. When the evaluator also offers `evaluate_batch(design, scenarios)`, the pool
    and each compass ring are evaluated in one batch (a simulator run is expensive; the wall time matters).
    """
    if n_random < 1:
        raise ValueError("the random pool needs at least one scenario")
    sampler = ScenarioSampler(space, seed)
    history: list[tuple[Scenario, float]] = []
    evaluations = 0
    batch = getattr(evaluate, "evaluate_batch", None)

    def run_batch(scenarios: Sequence[Scenario]) -> list[float]:
        nonlocal evaluations
        if batch is not None:
            values = [float(v) for v in batch(design, list(scenarios))]
        else:
            values = [float(evaluate(design, sc)) for sc in scenarios]
        evaluations += len(scenarios)
        return values

    # coarse stage: a seeded random pool over the whole space
    points = [sampler.sample_point() for _ in range(n_random)]
    pool = [sampler.scenario_from_point(p) for p in points]
    values = run_batch(pool)
    history.extend(zip(pool, values))
    best_value = min(values)
    best_index = values.index(best_value)
    best_point = points[best_index]
    random_value = best_value
    if best_point is None or math.isinf(best_value):
        # every scenario of the pool failed (the evaluator may return +inf for "does not walk"): keep the first one as the
        # worst found, there is nothing better to report.
        best_point, best_value = points[0], values[0]

    # fine stage: compass search around the worst member of the pool
    step_scale = 1.0
    while evaluations < n_random + n_refine and step_scale >= min_step_scale:
        candidates = _neighbours(space, best_point, step_scale)
        if not candidates:
            break
        scenarios = [scenario_from_point(c, space.nominal) for c in candidates]
        values = run_batch(scenarios)
        history.extend(zip(scenarios, values))
        improved = False
        for cand, sc, v in zip(candidates, scenarios, values):
            if v < best_value:
                best_value, best_point = v, cand
                improved = True
        if not improved:
            step_scale *= 0.5
    return AdversarialResult(
        scenario=scenario_from_point(best_point, space.nominal),
        value=best_value,
        evaluations=evaluations,
        random_value=random_value,
        history=history,
    )


# ---------------------------------------------------------------------------------------------------------------------
# Robust objectives
# ---------------------------------------------------------------------------------------------------------------------


class RobustObjective:
    """The three objectives of O-07 over one scenario set, behind one design evaluator.

    - `nominal`: the outcome at the nominal scenario of the space.
    - `cvar`: the lower-tail CVaR of the outcomes over the scenario set (higher is better; it is the mean of the worst
      outcomes).
    - `worst_case`: the smallest outcome over the scenario set (maximin).

    `evaluate(genome, scenario) -> forward distance` is the injected physics; the counter `scenario_evaluations` records how
    many scenario evaluations the objective has cost.
    """

    def __init__(
        self,
        space: ScenarioSpace,
        scenarios: Sequence[Scenario],
        evaluate: Evaluator,
        *,
        alpha: float = DEFAULT_ALPHA,
    ) -> None:
        self.space = space
        self.scenarios = list(scenarios)
        self.evaluate = evaluate
        self.alpha = float(alpha)
        self.scenario_evaluations = 0

    def _value(self, genome: Sequence[float], scenario: Scenario) -> float:
        self.scenario_evaluations += 1
        return float(self.evaluate(genome, scenario))

    def outcomes(self, genome: Sequence[float]) -> list[float]:
        """The outcome of the design in every scenario of the set, in the order of the set."""
        batch = getattr(self.evaluate, "evaluate_batch", None)
        if batch is not None:
            values = [float(v) for v in batch(genome, self.scenarios)]
            self.scenario_evaluations += len(values)
            return values
        return [self._value(genome, sc) for sc in self.scenarios]

    def nominal(self, genome: Sequence[float]) -> float:
        return self._value(genome, self.space.nominal)

    def cvar(self, genome: Sequence[float]) -> float:
        values = self.outcomes(genome)
        if not values:
            raise ValueError("the scenario set is empty")
        return cvar_lower(values, self.alpha)

    def worst_case(self, genome: Sequence[float]) -> float:
        values = self.outcomes(genome)
        if not values:
            raise ValueError("the scenario set is empty")
        return min(values)

    def mean(self, genome: Sequence[float]) -> float:
        values = self.outcomes(genome)
        if not values:
            raise ValueError("the scenario set is empty")
        return sum(values) / len(values)

    def objective(self, name: str) -> Callable[[Sequence[float]], float]:
        if name == "nominal":
            return self.nominal
        if name == "cvar":
            return self.cvar
        if name == "worst_case":
            return self.worst_case
        if name == "mean":
            return self.mean
        raise KeyError(f"unknown objective '{name}' (known: nominal, cvar, worst_case, mean)")


@dataclass
class OptimisationRun:
    """The outcome of one CMA-ES run against one objective."""

    objective: str
    genome: list[float]
    value: float
    candidate_evaluations: int
    scenario_evaluations: int
    wall_time_s: float
    history: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "genome": list(self.genome),
            "value": self.value,
            "candidate_evaluations": self.candidate_evaluations,
            "scenario_evaluations": self.scenario_evaluations,
            "wall_time_s": self.wall_time_s,
            "history": list(self.history),
        }


def robust_optimise(
    *,
    space: ScenarioSpace,
    scenarios: Sequence[Scenario],
    evaluate: Evaluator,
    x0: Sequence[float],
    sigma0: float,
    bounds: tuple[Sequence[float], Sequence[float]],
    alpha: float = DEFAULT_ALPHA,
    seed: int = 1,
    max_evals: int = 48,
    popsize: int = 8,
    objectives: Sequence[str] = ("nominal", "cvar", "worst_case"),
    optimizer: Optimizer | None = None,
) -> dict[str, OptimisationRun]:
    """Run the same ask/tell optimiser against each objective and return the three designs.

    The three runs share the seed, the starting point, the bounds and the evaluation budget, so the comparison between them
    is about the *objective*, not about the search effort. The budget is a number of candidate evaluations; a CVaR or
    worst-case candidate costs one physics evaluation per scenario, so it is the most expensive run by a factor of
    `len(scenarios)`.

    `optimizer` may be a pre-built ask/tell optimiser (for tests); by default a CMA-ES is built per objective.
    """
    import time

    runs: dict[str, OptimisationRun] = {}
    for name in objectives:
        obj = RobustObjective(space, scenarios, evaluate, alpha=alpha)
        fitness = obj.objective(name)
        opt = optimizer if optimizer is not None else CmaEs(
            list(map(float, x0)), float(sigma0), bounds, seed=seed, popsize=popsize
        )
        t0 = time.time()
        best, best_f, history = optimize(opt, fitness, max_evals)
        runs[name] = OptimisationRun(
            objective=name,
            genome=list(map(float, best)),
            value=float(best_f),
            candidate_evaluations=int(opt.evals),
            scenario_evaluations=obj.scenario_evaluations,
            wall_time_s=time.time() - t0,
            history=list(history),
        )
    return runs


@dataclass
class DesignRow:
    """One row of the three-way comparison table."""

    name: str
    genome: list[float]
    nominal: float
    cvar: float
    worst_case: float
    mean: float
    scenario_values: dict[str, float]
    extra_values: dict[str, float] = field(default_factory=dict)
    failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "genome": list(self.genome),
            "nominal": self.nominal,
            "cvar": self.cvar,
            "worst_case": self.worst_case,
            "mean": self.mean,
            "failures": self.failures,
            "scenario_values": dict(self.scenario_values),
            "extra_values": dict(self.extra_values),
        }


def compare_designs(
    designs: Mapping[str, Sequence[float]],
    *,
    space: ScenarioSpace,
    scenarios: Sequence[Scenario],
    evaluate: Evaluator,
    alpha: float = DEFAULT_ALPHA,
    extra: Mapping[str, Scenario] = {},
    failure_threshold: float | None = None,
) -> list[DesignRow]:
    """Evaluate every design at the nominal scenario and over the scenario set.

    The rows carry the three numbers the card compares: the nominal outcome, the CVaR over the set and the worst case of the
    set, plus the outcome in every scenario so a reader can see *where* the worst case comes from. `extra` holds named
    scenarios (for instance the adversarial scenario that broke the nominal design); their outcomes are reported next to the
    table but they stay out of the CVaR, which must describe the declared scenario set only.

    `failure_threshold` (optional) counts the scenarios of the set in which the design does not walk -- the number makes
    the CVaR readable: a tail that sits on a failure is a different kind of robust than a tail that sits on a bad stride.
    """
    rows: list[DesignRow] = []
    batch = getattr(evaluate, "evaluate_batch", None)
    for name, genome in designs.items():
        scenario_list = list(scenarios)
        extra_list = list(extra.items())
        # one batch call per design when the evaluator can do it: a simulator run is the expensive part
        ordered = scenario_list + [sc for _, sc in extra_list] + [space.nominal]
        if batch is not None:
            values_all = [float(v) for v in batch(genome, ordered)]
        else:
            values_all = [float(evaluate(genome, sc)) for sc in ordered]
        values = {sc.describe(): values_all[i] for i, sc in enumerate(scenario_list)}
        extra_values = {label: values_all[len(scenario_list) + i] for i, (label, _) in enumerate(extra_list)}
        nominal_value = values_all[-1]
        sample = list(values.values())
        failures = 0
        if failure_threshold is not None:
            failures = sum(1 for v in sample if v <= float(failure_threshold))
        rows.append(
            DesignRow(
                name=name,
                genome=list(map(float, genome)),
                nominal=nominal_value,
                cvar=cvar_lower(sample, alpha) if sample else float("nan"),
                worst_case=min(sample) if sample else float("nan"),
                mean=sum(sample) / len(sample) if sample else float("nan"),
                scenario_values=values,
                extra_values=extra_values,
                failures=failures,
            )
        )
    return rows
