"""W-08: the sail parameters as genes (the sail gene space and the combined objective).

Everything in the fast part of this file runs on injected fake evaluators: no physics, no MuJoCo, no network. The
one test that needs the real simulator is marked `slow` and is skipped by the fast suite (`-m "not slow"`).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from strandbeest_opt.robust import DEFAULT_ALPHA, Axis, Scenario, ScenarioSpace, cvar_lower
from strandbeest_opt.sailgenes import (
    DOES_NOT_WALK_M,
    INFEASIBLE_SCORE,
    Anchors,
    GeneBound,
    ObjectiveWeights,
    SailObjective,
    SailParameters,
    SailSpace,
)

ROOT = Path(__file__).resolve().parents[3]
DESIGN_PATH = ROOT / "schemas/examples/design-jansen-small-6leg.json"


def _base_design() -> dict:
    return json.loads(DESIGN_PATH.read_text())


def _space(with_sail: bool = True) -> SailSpace:
    """The declared space of W-08: the three linkage lengths of O-07 plus the two sail genes."""
    sail_genes = (
        (
            GeneBound(
                name="sail_area_m2",
                low=0.010,
                high=0.080,
                unit="m2",
                reference=0.03,
                assumption="assumption: a printed sail panel on a 0.25 m long walker",
            ),
            GeneBound(
                name="sail_gear",
                low=4.0,
                high=24.0,
                unit="1",
                reference=10.0,
                assumption="assumption: the sail-to-crank reduction ratio [unverified]",
            ),
        )
        if with_sail
        else ()
    )
    return SailSpace(
        base_design=_base_design(),
        link_genes=(
            GeneBound(name="m", low=12.0, high=18.0, unit="length units", reference=15.0,
                      assumption="assumption: a declared box around the reference crank length"),
            GeneBound(name="a", low=36.0, high=40.0, unit="length units", reference=38.0,
                      assumption="assumption: a declared box around the reference hip offset"),
            GeneBound(name="h", low=60.0, high=70.0, unit="length units", reference=65.7,
                      assumption="assumption: a declared box around the reference thigh"),
        ),
        sail_genes=sail_genes,
    )


def _scenario_space() -> ScenarioSpace:
    return ScenarioSpace(
        name="w08-wind-only-v1",
        axes=(
            Axis(name="wind_speed_m_s", kind="continuous", low=0.5, high=8.0, unit="m/s",
                 assumption="assumption: from the reference start wind upwards"),
            Axis(name="wind_kind", kind="categorical", values=("constant", "gusts"),
                 assumption="assumption: the wind models of strandbeest_sim.winds"),
        ),
        nominal=Scenario(wind_speed_m_s=5.0, wind_kind="constant", wind_params={"yaw_deg": 0.0}),
    )


def _scenarios(n: int = 4) -> list[Scenario]:
    space = _scenario_space()
    return [
        Scenario(wind_speed_m_s=1.0 + i, wind_kind="gusts" if i % 2 else "constant",
                 wind_params={"yaw_deg": 0.0, "amplitude": 1.0, "period": 6.0})
        for i in range(n)
    ]


# ---------------------------------------------------------------------------------------------------------------------
# The gene space
# ---------------------------------------------------------------------------------------------------------------------


def test_the_genome_round_trips_through_the_scenario_overrides():
    """genome -> the sail fields it sets -> back to the genome."""
    space = _space()
    genome = [15.0, 38.0, 65.7, 0.045, 14.0]

    overrides = space.to_overrides(genome)
    assert overrides == {"drive": {"sail_area": 0.045, "sail_gear": 14.0}}

    sail = space.from_overrides(overrides)
    assert sail == SailParameters(area_m2=0.045, gear=14.0)

    back = space.genome_with_sail(space.link_values(genome), sail)
    assert back == genome


def test_the_genome_round_trips_through_the_design_document():
    space = _space()
    genome = [16.0, 39.0, 64.0, 0.05, 12.0]
    doc = space.to_design(genome)
    assert doc["linkage"]["params"]["m"] == 16.0
    assert doc["linkage"]["params"]["a"] == 39.0
    assert doc["linkage"]["params"]["h"] == 64.0
    # the untouched lengths stay at the reference values
    assert doc["linkage"]["params"]["b"] == _base_design()["linkage"]["params"]["b"]
    assert doc["drive"]["sail"]["area_m2"] == 0.05
    assert doc["drive"]["sail"]["gear"] == 12.0
    # the design document is a copy: the base design is never mutated
    assert _base_design()["drive"]["sail"]["area_m2"] == 0.03


def test_a_fixed_sail_space_keeps_the_reference_sail():
    space = _space(with_sail=False)
    assert space.dimension == 3
    assert space.sail_genes == ()
    assert space.sail_of([15.0, 38.0, 65.7]) == SailParameters(area_m2=0.03, gear=10.0)
    assert space.to_overrides([15.0, 38.0, 65.7]) == {"drive": {"sail_area": 0.03, "sail_gear": 10.0}}


def test_the_sampler_respects_the_declared_bounds():
    space = _space()
    genomes = space.sample_genomes(300, seed=7)
    assert len(genomes) == 300
    lower, upper = space.bounds()
    for genome in genomes:
        assert len(genome) == space.dimension
        for value, lo, hi in zip(genome, lower, upper):
            assert lo <= value <= hi
    # the same seed gives the same sample, a different seed does not
    assert space.sample_genomes(5, seed=7) == genomes[:5]
    assert space.sample_genomes(5, seed=8) != genomes[:5]


def test_the_sampler_respects_the_bounds_of_a_fixed_sail_space():
    space = _space(with_sail=False)
    for genome in space.sample_genomes(50, seed=3):
        assert len(genome) == 3
        assert 12.0 <= genome[0] <= 18.0


def test_a_gene_without_an_assumption_is_refused():
    with pytest.raises(ValueError, match="assumption"):
        GeneBound(name="x", low=0.0, high=1.0, unit="1", assumption="  ", reference=0.5)


def test_a_gene_whose_reference_value_lies_outside_its_range_is_refused():
    with pytest.raises(ValueError, match="outside"):
        GeneBound(name="x", low=0.0, high=1.0, unit="1", assumption="assumption: x", reference=2.0)


def test_the_unit_cube_mapping_round_trips():
    space = _space()
    genome = [13.0, 37.0, 62.0, 0.02, 6.0]
    unit = space.to_unit(genome)
    assert all(0.0 <= u <= 1.0 for u in unit)
    assert space.from_unit(unit) == pytest.approx(genome)


def test_the_bounds_of_the_gene_space_are_declared_with_an_assumption():
    space = _space()
    assumptions = space.assumptions()
    for name in space.names:
        assert name in assumptions
        assert assumptions[name].strip()
    assert assumptions["sail_area_m2"].strip()
    assert assumptions["sail_gear"].strip()


# ---------------------------------------------------------------------------------------------------------------------
# The objective
# ---------------------------------------------------------------------------------------------------------------------


def _fake_landscape():
    """A fake landscape with a real trade-off: a bigger sail starts in less wind but walks worse in a gust.

    The genome is `[m, a, h, area, gear]`; the start wind falls with the sail area and the gear, while the gust
    outcome falls with the sail area (a big sail catches the gust and pushes the walker back).
    """
    def evaluate(genome, scenario):
        area = float(genome[3])
        gear = float(genome[4])
        base = 1.0 - 4.0 * (area - 0.03) + 0.01 * (10.0 - gear)
        gust = 1.0 if scenario.wind_kind == "gusts" else 0.0
        return base - 2.0 * gust * (area - 0.03)

    def start_wind(genome):
        area = float(genome[3])
        gear = float(genome[4])
        return 0.5 * math.sqrt(0.03 / area) * math.sqrt(10.0 / gear)

    return evaluate, start_wind


def _anchors(space: SailSpace, scenarios, evaluate, start_wind) -> Anchors:
    """The anchors of the objective, computed from the reference design on the same (fake) landscape."""
    reference = space.reference_genome
    outcomes = [float(evaluate(reference, sc)) for sc in scenarios]
    nominal = _scenario_space().nominal
    return Anchors(
        start_wind_m_s=float(start_wind(reference)),
        cvar_m=cvar_lower(outcomes, DEFAULT_ALPHA),
        distance_m=float(evaluate(reference, nominal)),
    )


def test_the_objective_is_deterministic_under_a_fixed_seed():
    space = _space()
    scenarios = _scenarios()
    evaluate, start_wind = _fake_landscape()
    genome = space.sample_genomes(1, seed=11)[0]

    scores = []
    for _ in range(3):
        obj = SailObjective(space, scenarios, evaluate, start_wind, anchors=_anchors(space, scenarios, evaluate, start_wind))
        scores.append(obj.score(genome))
    assert scores[0] == scores[1] == scores[2]

    # the same seed also gives the same scenario set (the sampler is seeded, there is no global RNG)
    first = _scenarios()
    second = _scenarios()
    assert [s.describe() for s in first] == [s.describe() for s in second]


def test_the_objective_rejects_an_infeasible_genome():
    """A candidate that cannot be evaluated at all scores INFEASIBLE_SCORE, and the space refuses a bad genome."""
    space = _space()
    scenarios = _scenarios()

    def broken_evaluate(genome, scenario):
        return float("-inf")  # the linkage does not assemble

    _, start_wind = _fake_landscape()
    evaluate, _ = _fake_landscape()
    obj = SailObjective(space, scenarios, broken_evaluate, start_wind,
                        anchors=_anchors(space, scenarios, evaluate, start_wind))
    assert obj.score(space.reference_genome) == INFEASIBLE_SCORE

    def crashing_evaluate(genome, scenario):
        raise RuntimeError("the solver blew up")

    obj = SailObjective(space, scenarios, crashing_evaluate, start_wind,
                        anchors=_anchors(space, scenarios, evaluate, start_wind))
    assert obj.score(space.reference_genome) == INFEASIBLE_SCORE

    # a genome outside the declared box is rejected by the space, not silently clipped
    with pytest.raises(ValueError, match="outside its declared range"):
        space.validate([15.0, 38.0, 65.7, 0.5, 10.0])
    with pytest.raises(ValueError, match="expected"):
        space.validate([15.0, 38.0])


def test_the_objective_rejects_a_genome_outside_the_declared_box():
    space = _space()
    scenarios = _scenarios()
    evaluate, start_wind = _fake_landscape()
    obj = SailObjective(space, scenarios, evaluate, start_wind, anchors=_anchors(space, scenarios, evaluate, start_wind))
    with pytest.raises(ValueError, match="outside its declared range"):
        obj.score([15.0, 38.0, 65.7, 0.5, 10.0])


def test_the_weighting_behaves_as_documented():
    """The weighting is a design decision: it trades the start wind against the gust robustness.

    On a landscape with a real trade-off, the **nominal** objective (the start wind alone) and the **robust**
    objective (the gust robustness alone) have different optima: the robust optimum starts in a **worse** wind than
    the nominal one. This is the documented behaviour: the card's wording ("a start wind that is 20 % worse but a
    CVaR that is 30 % better is a design decision, not a fact") is exactly what the objective does, and the test says
    so instead of asserting a property that does not hold.
    """
    space = _space()
    scenarios = _scenarios()
    evaluate, start_wind = _fake_landscape()
    anchors = _anchors(space, scenarios, evaluate, start_wind)

    def best_under(robust: float) -> tuple[float, float]:
        """A brute-force search for the best genome on a grid (the test does not need CMA-ES).

        Returns the start wind and the CVaR of that optimum.
        """
        obj = SailObjective(space, scenarios, evaluate, start_wind,
                            weights=ObjectiveWeights.of_robust(robust), anchors=anchors)
        best = None
        for i in range(21):
            for j in range(21):
                genome = [15.0, 38.0, 65.7, 0.010 + 0.070 * i / 20, 4.0 + 20.0 * j / 20]
                score = obj.score(genome)
                if best is None or score > best[0]:
                    best = (score, obj.start_wind_value(genome), obj.cvar_of(obj.outcomes(genome)))
        return best[1], best[2]

    nominal_start, nominal_cvar = best_under(0.0)
    robust_start, robust_cvar = best_under(1.0)

    # the nominal optimum starts in the lowest wind ...
    assert nominal_start <= robust_start
    # ... and the robust optimum has the best gust robustness. The two optima are different designs.
    assert robust_cvar >= nominal_cvar
    assert robust_start > nominal_start  # the robust optimum pays for its robustness with the start wind

    # and the two terms of one genome move in opposite directions when the weight changes: a bigger sail starts
    # earlier but walks worse in a gust, so the nominal weighting likes it and the robust weighting does not.
    obj_nominal = SailObjective(space, scenarios, evaluate, start_wind,
                                weights=ObjectiveWeights.of_robust(0.0), anchors=anchors)
    obj_robust = SailObjective(space, scenarios, evaluate, start_wind,
                               weights=ObjectiveWeights.of_robust(1.0), anchors=anchors)
    genome = [15.0, 38.0, 65.7, 0.06, 10.0]
    assert obj_nominal.score(genome) > obj_robust.score(genome)
    assert obj_nominal.start_term(obj_nominal.start_wind_value(genome)) > 0.0  # it starts in less wind
    assert obj_robust.robust_term(obj_robust.cvar_of(obj_robust.outcomes(genome))) < 0.0  # it walks worse


def test_the_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        ObjectiveWeights(start=0.5, robust=0.9)
    with pytest.raises(ValueError, match="negative"):
        ObjectiveWeights(start=-0.5, robust=1.5)
    assert ObjectiveWeights.of_robust(0.25) == ObjectiveWeights(start=0.75, robust=0.25)


def test_the_robust_term_is_the_cvar_of_the_scenario_set():
    space = _space()
    scenarios = _scenarios(4)
    evaluate, start_wind = _fake_landscape()
    obj = SailObjective(space, scenarios, evaluate, start_wind, alpha=DEFAULT_ALPHA, anchors=_anchors(space, scenarios, evaluate, start_wind))
    genome = [15.0, 38.0, 65.7, 0.03, 10.0]
    outcomes = obj.outcomes(genome)
    assert obj.cvar_of(outcomes) == pytest.approx(min(outcomes))  # alpha * n = 0.4 -> the tail mass is one sample
    assert obj.report(genome)["cvar_m"] == pytest.approx(obj.cvar_of(outcomes))


def test_a_design_that_never_starts_gets_the_worst_start_term():
    space = _space()
    scenarios = _scenarios()
    evaluate, start_wind = _fake_landscape()

    def never_starts(genome):
        return math.inf

    obj = SailObjective(space, scenarios, evaluate, never_starts, anchors=_anchors(space, scenarios, evaluate, start_wind))
    assert obj.start_term(math.inf) == -2.0
    assert obj.score(space.reference_genome) < 0.0


def test_the_does_not_walk_outcome_is_far_below_any_real_distance():
    assert DOES_NOT_WALK_M < -0.5


# ---------------------------------------------------------------------------------------------------------------------
# The slow test: the real simulator (skipped by the fast suite)
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_the_sail_genes_change_the_start_wind_of_the_real_walker():
    """The real physics: a bigger sail starts in a lower wind (the same 1/sqrt(A) law as W-03).

    This needs the simulator, so it is marked `slow` and the fast suite (`-m "not slow"`) skips it.
    """
    import sys

    sys.path.insert(0, str(ROOT / "packages/common/src"))
    sys.path.insert(0, str(ROOT / "packages/sim/src"))
    from strandbeest_common import Design
    from strandbeest_sim.backends.k2_backend import K2Backend
    from strandbeest_sim.from_design import scenario_from_design
    from strandbeest_sim.runner import run

    space = _space()

    def distance_at(genome, wind: float) -> float:
        doc = space.to_design(genome)
        overrides = {
            "drive": {"kind": "sail"},
            "wind": {"kind": "constant", "speed": wind, "params": {"yaw_deg": 0.0}},
            "run": {"revolutions": 10.0, "settle": 0.2, "max_time": 2.5, "frame_rate": 0, "give_up_after": 1.5},
        }
        result = run(scenario_from_design(Design(doc), overrides), backend=K2Backend(timestep=1e-3))
        return float(result.x[-1] - result.x[0])

    small = distance_at([15.0, 38.0, 65.7, 0.01, 10.0], 5.0)
    big = distance_at([15.0, 38.0, 65.7, 0.08, 10.0], 5.0)
    assert big > small  # the bigger sail drives the walker further in the same wind
