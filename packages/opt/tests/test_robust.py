"""O-07: robust optimisation and adversarial scenario search.

Everything here runs on injected fake evaluators: no physics, no MuJoCo, no network. The slow tests (marked `slow`) are the
ones that would need a simulator and are skipped by the fast suite.
"""

from __future__ import annotations

import math

import pytest
from strandbeest_opt.robust import (
    DEFAULT_ALPHA,
    Axis,
    Scenario,
    ScenarioSampler,
    ScenarioSpace,
    adversarial_search,
    compare_designs,
    cvar_lower,
    cvar_lower_empirical,
    robust_optimise,
    scenario_from_point,
)


DESIGN = [1.0, 0.5]  # the design under test in the fake-landscape tests


# ---------------------------------------------------------------------------------------------------------------------
# CVaR
# ---------------------------------------------------------------------------------------------------------------------


def test_cvar_lower_matches_the_hand_computed_closed_form():
    # m = alpha * n = 2 exactly: the mean of the two smallest samples.
    assert cvar_lower([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(1.5)
    # m = 1.5: one whole sample plus half of the second one, divided by 1.5.
    assert cvar_lower([1.0, 2.0, 3.0, 4.0, 5.0], 0.3) == pytest.approx((1.0 + 0.5 * 2.0) / 1.5)
    # m < 1: the tail mass falls on the smallest sample alone.
    assert cvar_lower([10.0], 0.1) == pytest.approx(10.0)
    assert cvar_lower([10.0, 20.0], 0.1) == pytest.approx(10.0)
    # alpha = 1 is the plain mean.
    assert cvar_lower([1.0, 2.0, 3.0, 4.0], 1.0) == pytest.approx(2.5)
    # the WIND.md wording: the mean of the worst 10 % of ten samples.
    assert cvar_lower([float(v) for v in range(1, 11)], 0.1) == pytest.approx(1.0)
    # twenty samples: the mean of the two worst.
    assert cvar_lower([float(v) for v in range(1, 21)], 0.1) == pytest.approx(1.5)


def test_cvar_lower_agrees_with_the_rockafellar_uryasev_optimisation_form():
    """A second, independent formulation of the same quantity: the closed form must equal max_z {z - E[(z-X)+]/alpha}."""
    import random as _random

    rng = _random.Random(20261021)
    for _ in range(20):
        n = rng.randint(2, 40)
        alpha = rng.choice([0.1, 0.2, 0.25, 0.3, 0.5])
        values = [rng.uniform(-5.0, 5.0) for _ in range(n)]
        closed_form = cvar_lower(values, alpha)
        # the Rockafellar-Uryasev programme, solved exactly: its maximiser is an order statistic of the sample
        best = max(
            z - sum(max(z - v, 0.0) for v in values) / (alpha * n)
            for z in values
        )
        assert closed_form == pytest.approx(best, abs=1e-12)


def test_cvar_lower_is_the_lower_tail_and_never_above_the_mean():
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    value = cvar_lower(values, DEFAULT_ALPHA)
    assert value <= sum(values) / len(values)
    assert value >= min(values)
    assert value == pytest.approx(1.0)  # m = 0.8 < 1 -> the smallest sample


def test_cvar_lower_rejects_bad_arguments():
    with pytest.raises(ValueError):
        cvar_lower([], 0.1)
    with pytest.raises(ValueError):
        cvar_lower([1.0], 0.0)
    with pytest.raises(ValueError):
        cvar_lower([1.0], 1.5)


def test_cvar_lower_empirical_is_the_plain_tail_mean_and_differs_from_the_closed_form():
    values = [float(v) for v in range(1, 6)]
    # alpha * n = 1.5: the closed form gives the second sample a half weight, the plain estimator averages the two worst.
    assert cvar_lower(values, 0.3) == pytest.approx(4.0 / 3.0)
    assert cvar_lower_empirical(values, 0.3) == pytest.approx(1.5)
    # when alpha * n is an integer the two agree
    ten = [float(v) for v in range(1, 11)]
    assert cvar_lower(ten, 0.1) == pytest.approx(cvar_lower_empirical(ten, 0.1))


# ---------------------------------------------------------------------------------------------------------------------
# The scenario space
# ---------------------------------------------------------------------------------------------------------------------


def _space() -> ScenarioSpace:
    """A small declared space: every axis names its assumption (AGENTS.md)."""
    return ScenarioSpace(
        name="test-space",
        axes=(
            Axis(name="wind_speed_m_s", kind="continuous", low=0.0, high=20.0, unit="m/s",
                 assumption="test range, not a physical claim"),
            Axis(name="friction", kind="continuous", low=0.1, high=3.0, unit="-",
                 assumption="test range, not a physical claim"),
            Axis(name="terrain_kind", kind="categorical", values=("flat", "slope", "bumps"),
                 assumption="test categories"),
            Axis(name="turbulence_seed", kind="integer", low=1, high=8,
                 assumption="test realisation index"),
        ),
        nominal=Scenario(wind_speed_m_s=5.0, wind_kind="constant", terrain_kind="flat", friction=1.5,
                         label="nominal"),
        notes="a test space",
    )


def test_an_axis_without_an_assumption_is_refused():
    with pytest.raises(ValueError):
        Axis(name="wind_speed_m_s", kind="continuous", low=0.0, high=1.0, assumption="   ")
    with pytest.raises(ValueError):
        Axis(name="terrain_kind", kind="categorical", values=(), assumption="empty categories")


def test_the_sampler_is_reproducible_and_respects_the_declared_bounds():
    space = _space()
    a = ScenarioSampler(space, seed=7).sample(40)
    b = ScenarioSampler(space, seed=7).sample(40)
    c = ScenarioSampler(space, seed=8).sample(40)
    assert [s.to_dict() for s in a] == [s.to_dict() for s in b]
    assert [s.to_dict() for s in a] != [s.to_dict() for s in c]
    for s in a:
        assert 0.0 <= s.wind_speed_m_s <= 20.0
        assert 0.1 <= s.friction <= 3.0
        assert s.terrain_kind in ("flat", "slope", "bumps")
        assert 1 <= s.wind_params["yaw_deg"] * 0 + 1  # the yaw is always present in the wind parameters
        assert "yaw_deg" in s.wind_params


def test_the_sampled_scenario_carries_the_kind_specific_parameters():
    space = _space()
    sampler = ScenarioSampler(space, seed=3)
    for _ in range(50):
        point = sampler.sample_point()
        point["wind_kind"] = "gusts"
        sc = scenario_from_point(point, space.nominal)
        assert sc.wind_kind == "gusts"
        assert "amplitude" in sc.wind_params and "period" in sc.wind_params
        point["wind_kind"] = "profile_turbulent"
        sc = scenario_from_point(point, space.nominal)
        assert "intensity" in sc.wind_params and "seed" in sc.wind_params
        point["terrain_kind"] = "bumps"
        sc = scenario_from_point(point, space.nominal)
        assert sc.terrain_params["count"] >= 1


def test_a_scenario_translates_into_simulator_overrides():
    sc = Scenario(wind_speed_m_s=7.5, wind_kind="gusts", wind_params={"amplitude": 2.0, "period": 5.0, "yaw_deg": 30.0},
                  terrain_kind="slope", friction=0.8, slope_deg=4.0)
    ov = sc.overrides()
    assert ov["wind"] == {"kind": "gusts", "speed": 7.5, "params": {"amplitude": 2.0, "period": 5.0, "yaw_deg": 30.0}}
    assert ov["terrain"] == {"kind": "slope", "friction": 0.8, "slope_deg": 4.0, "params": {}}


# ---------------------------------------------------------------------------------------------------------------------
# Adversarial scenario search
# ---------------------------------------------------------------------------------------------------------------------


def _bowl(design, sc: Scenario) -> float:
    """A fake landscape whose minimum is known: the worst point is bumps at 17 m/s and friction 0.2."""
    terrain_term = 0.0 if sc.terrain_kind != "bumps" else -5.0
    return (sc.wind_speed_m_s - 17.0) ** 2 + (sc.friction - 0.2) ** 2 + terrain_term


def test_the_adversarial_search_finds_a_worse_scenario_than_the_random_pool_alone():
    space = _space()
    result = adversarial_search(space, DESIGN, _bowl, seed=11, n_random=24, n_refine=120)
    assert result.evaluations == len(result.history)
    assert result.improved, "the refinement did not beat the random pool"
    assert result.value < result.random_value
    # the known worst point is found (within the final step of the compass search)
    assert abs(result.scenario.wind_speed_m_s - 17.0) < 0.5
    assert abs(result.scenario.friction - 0.2) < 0.2
    assert result.scenario.terrain_kind == "bumps"
    # the found scenario is at least as bad as every scenario the pool drew
    pool_values = [v for _, v in result.history]
    assert result.value <= min(pool_values)


def test_the_adversarial_search_is_reproducible_and_stays_inside_the_bounds():
    space = _space()
    a = adversarial_search(space, DESIGN, _bowl, seed=5, n_random=16, n_refine=60)
    b = adversarial_search(space, DESIGN, _bowl, seed=5, n_random=16, n_refine=60)
    assert a.value == pytest.approx(b.value)
    assert a.scenario.to_dict() == b.scenario.to_dict()
    for sc, _ in a.history:
        assert 0.0 <= sc.wind_speed_m_s <= 20.0
        assert 0.1 <= sc.friction <= 3.0
        assert sc.terrain_kind in ("flat", "slope", "bumps")


def test_the_adversarial_search_can_be_told_to_look_for_a_failure():
    """A landscape where the walker fails (distance 0) in one region: the search must find that region."""

    def fail_low_wind(design, sc: Scenario) -> float:
        if sc.wind_speed_m_s < 1.0:
            return 0.0  # the walker does not move at all
        return sc.wind_speed_m_s

    space = _space()
    result = adversarial_search(space, DESIGN, fail_low_wind, seed=2, n_random=20, n_refine=60)
    assert result.value == pytest.approx(0.0)
    assert result.scenario.wind_speed_m_s < 1.0


# ---------------------------------------------------------------------------------------------------------------------
# The robust optimisation loop
# ---------------------------------------------------------------------------------------------------------------------


def _fake_evaluator(genome, scenario: Scenario) -> float:
    """A deterministic fake: the design likes a wide gait, the scenario punishes a low wind."""
    stance = float(genome[0])
    return stance * (1.0 - 0.5 * min(1.0, scenario.wind_speed_m_s / 5.0))


def test_the_optimiser_is_deterministic_under_a_fixed_seed():
    space = _space()
    scenarios = ScenarioSampler(space, seed=2).sample(4)
    kwargs = dict(
        space=space,
        scenarios=scenarios,
        evaluate=_fake_evaluator,
        x0=[1.0, 0.5],
        sigma0=0.2,
        bounds=([0.1, 0.1], [2.0, 2.0]),
        seed=4,
        max_evals=24,
        popsize=6,
    )
    a = robust_optimise(**kwargs)
    b = robust_optimise(**kwargs)
    assert set(a) == {"nominal", "cvar", "worst_case"}
    for name in a:
        assert a[name].genome == b[name].genome
        assert a[name].value == pytest.approx(b[name].value)
    # a different seed explores differently
    c = robust_optimise(**{**kwargs, "seed": 5})
    assert (c["nominal"].genome != a["nominal"].genome) or (c["nominal"].value != a["nominal"].value)


def test_the_three_objectives_cost_what_they_should():
    space = _space()
    scenarios = ScenarioSampler(space, seed=2).sample(4)
    runs = robust_optimise(
        space=space,
        scenarios=scenarios,
        evaluate=_fake_evaluator,
        x0=[1.0, 0.5],
        sigma0=0.2,
        bounds=([0.1, 0.1], [2.0, 2.0]),
        seed=4,
        max_evals=12,
        popsize=6,
    )
    # the nominal objective evaluates one scenario per candidate, the other two evaluate the whole set
    assert runs["nominal"].scenario_evaluations == runs["nominal"].candidate_evaluations
    assert runs["cvar"].scenario_evaluations == runs["cvar"].candidate_evaluations * len(scenarios)
    assert runs["worst_case"].scenario_evaluations == runs["worst_case"].candidate_evaluations * len(scenarios)


def test_the_cvar_objective_is_the_mean_of_the_worst_outcomes():
    space = _space()
    scenarios = ScenarioSampler(space, seed=2).sample(10)
    runs = robust_optimise(
        space=space,
        scenarios=scenarios,
        evaluate=_fake_evaluator,
        x0=[1.0, 0.5],
        sigma0=0.05,
        bounds=([0.1, 0.1], [2.0, 2.0]),
        seed=1,
        max_evals=12,
        popsize=6,
        objectives=("cvar",),
    )
    genome = runs["cvar"].genome
    values = sorted(_fake_evaluator(genome, sc) for sc in scenarios)
    assert runs["cvar"].value == pytest.approx(cvar_lower(values, DEFAULT_ALPHA))
    # with ten samples and alpha = 0.1 the discrete estimator is the sample minimum
    assert runs["cvar"].value == pytest.approx(values[0])


def test_compare_designs_reports_the_nominal_the_cvar_and_the_worst_case():
    space = _space()
    scenarios = ScenarioSampler(space, seed=2).sample(6)
    rows = compare_designs(
        {"wide": [2.0, 0.5], "narrow": [0.5, 0.5]},
        space=space,
        scenarios=scenarios,
        evaluate=_fake_evaluator,
    )
    by_name = {r.name: r for r in rows}
    assert by_name["wide"].nominal > by_name["narrow"].nominal
    assert by_name["wide"].worst_case <= by_name["wide"].mean
    assert len(by_name["wide"].scenario_values) == len(scenarios)


def test_a_scenario_can_be_replaced_on_a_different_ground_friction():
    """The friction sensitivity check of the experiment: only the friction changes, and the label follows."""
    sc = Scenario(wind_speed_m_s=7.5, wind_kind="gusts", wind_params={"amplitude": 2.0, "period": 5.0, "yaw_deg": 30.0},
                  terrain_kind="slope", friction=1.5, slope_deg=4.0)
    other = sc.with_friction(0.5)
    assert other.friction == 0.5
    assert other.wind_speed_m_s == sc.wind_speed_m_s
    assert other.terrain_kind == sc.terrain_kind
    assert other.slope_deg == sc.slope_deg
    assert other.wind_params == sc.wind_params
    assert "mu=0.50" in other.label and "mu=1.50" not in other.label
    assert sc.friction == 1.5  # the original is untouched (the scenario is frozen)


def test_compare_designs_uses_the_batch_protocol_when_there_is_one():
    """A batch evaluator must give the same table as the plain one, and it must be asked for everything at once."""
    space = _space()
    scenarios = ScenarioSampler(space, seed=2).sample(6)
    calls: list[int] = []

    class _Batch:
        def __call__(self, genome, scenario: Scenario) -> float:
            return _fake_evaluator(genome, scenario)

        def evaluate_batch(self, genome, scenario_list) -> list[float]:
            calls.append(len(scenario_list))
            return [_fake_evaluator(genome, sc) for sc in scenario_list]

    plain = compare_designs({"wide": [2.0, 0.5]}, space=space, scenarios=scenarios, evaluate=_fake_evaluator)
    batched = compare_designs({"wide": [2.0, 0.5]}, space=space, scenarios=scenarios, evaluate=_Batch())
    assert len(calls) == 1
    assert calls[0] == len(scenarios) + 1  # the scenario set plus the nominal scenario
    assert plain[0].nominal == pytest.approx(batched[0].nominal)
    assert plain[0].cvar == pytest.approx(batched[0].cvar)
    assert plain[0].worst_case == pytest.approx(batched[0].worst_case)


# ---------------------------------------------------------------------------------------------------------------------
# Slow: these need a simulator and are skipped by the fast suite
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_the_adversarial_search_finds_a_failing_wind_for_the_reference_design():
    """The physical version of the acceptance criterion: a scenario in which the reference walker does not move."""
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "packages/common/src"))
    sys.path.insert(0, str(root / "packages/sim/src"))
    from strandbeest_common import Design
    from strandbeest_sim.backends.k2_backend import K2Backend
    from strandbeest_sim.from_design import scenario_from_design
    from strandbeest_sim.runner import run

    design = json.loads((root / "schemas/examples/design-jansen-small-6leg.json").read_text())
    space = ScenarioSpace(
        name="wind-only",
        axes=(
            Axis(name="wind_speed_m_s", kind="continuous", low=0.1, high=14.0, unit="m/s",
                 assumption="below the ~0.69 m/s start wind of the reference design the sail cannot start the crank"),
        ),
        nominal=Scenario(wind_speed_m_s=5.0),
    )

    def evaluate(_genome, sc: Scenario) -> float:
        """The physics of the reference design (the genome is ignored: this test only varies the scenario)."""
        ov = {
            "drive": {"kind": "sail"},
            "wind": {"kind": sc.wind_kind, "speed": sc.wind_speed_m_s, "params": dict(sc.wind_params)},
            "terrain": {"kind": "flat", "friction": 1.5},
            "run": {"revolutions": 3.0, "settle": 0.2, "max_time": 3.0, "frame_rate": 0},
        }
        res = run(scenario_from_design(Design(design), ov), backend=K2Backend(timestep=1e-3))
        return float(res.x[-1] - res.x[0])

    result = adversarial_search(space, DESIGN, evaluate, seed=1, n_random=6, n_refine=8)
    assert result.value < 0.01  # the walker does not walk in the worst wind it found
    assert result.scenario.wind_speed_m_s < 1.0
