"""W-08: the sail parameters as genes -- the sail area and the gear ratio join the link lengths in the search.

  python packages/opt/scripts/sail_gene_run.py [--seed 1] [--alpha 0.1] [--scenarios 20] [--gusts 8]
                                                [--evals 120] [--popsize 12] [--sigma0 0.15] [--workers 8]
                                                [--backend k2] [--timestep 0.001] [--window 2.5]
                                                [--no-cross-check] [--out experiments/sail-gene-optimization.json]

What it does, in order:

1. Declares the gene space: the three linkage lengths of O-07 plus the two sail genes (the sail area and the
   sail-to-crank reduction ratio), every bound with its assumption. Two spaces are built from it: the **fixed sail**
   space (no sail genes, the sail keeps the reference values) and the **free sail** space.
2. Declares the scenario space (the wind only) and samples the scenario set from it with a seeded RNG, stratified so
   that the gust scenarios are not left to chance. The CVaR of that set is the gust robustness (WIND.md section 5:
   the mean of the worst 10 %).
3. Runs the same CMA-ES (ask/tell, same seed, same budget, same population) over the two spaces at several weightings
   of the objective. The objective is the start wind and the gust robustness in one number, with an explicit,
   stated weighting. The start-wind term inside the loop is the **cheap quasi-static proxy** of the virtual
   dynamometer (EXPERIMENTS section 32): the real start-wind search (6 simulations of up to 40 s each) is far too
   expensive to sit in the loop, so it is run on the **final designs** as the verification step, and the two numbers
   are reported side by side.
4. Compares the two designs side by side (start wind, CVaR, forward distance) and answers the card's third question:
   in the worst gust sequence, does the design of the robust objective do no worse than the nominally optimal one?
5. Cross-checks the final table under MuJoCo (the second solver), because O-07 showed that a conclusion that only
   holds in one solver is not a ranking conclusion.

The physics is wind driven (the product layer, docs/WIND.md section 2). Everything is seeded, so a rerun with the
same arguments gives the same numbers. Writes experiments/sail-gene-optimization.json.

The search is budget-limited: the number of evaluations is reported and no convergence is claimed.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/common/src"))
sys.path.insert(0, str(ROOT / "packages/sim/src"))
sys.path.insert(0, str(ROOT / "packages/opt/src"))

from strandbeest_opt.optimizers import CmaEs  # noqa: E402
from strandbeest_opt.robust import (  # noqa: E402
    Axis,
    Scenario,
    ScenarioSampler,
    ScenarioSpace,
    adversarial_search,
    cvar_lower,
    scenario_from_point,
)
from strandbeest_opt.sailgenes import (  # noqa: E402
    Anchors,
    GeneBound,
    ObjectiveWeights,
    SailObjective,
    SailSpace,
)

DESIGN_PATH = ROOT / "schemas/examples/design-jansen-small-6leg.json"
_BASE_DESIGN = json.loads(DESIGN_PATH.read_text())

# The number of crank angles at which the linkage must assemble (the same count as strandbeest_opt.fitness.PROBES).
ASSEMBLY_PROBES = 24
# The outcome of a design that cannot be assembled: it does not walk at all, and the objective treats a non-finite
# outcome as "this candidate does not exist" (see strandbeest_opt.sailgenes.INFEASIBLE_SCORE).
DOES_NOT_EXIST = float("-inf")


# ---------------------------------------------------------------------------------------------------------------------
# The declared gene space
# ---------------------------------------------------------------------------------------------------------------------

# The linkage subspace: the same three parameters as O-07, so that the two experiments can be compared.
LINK_GENES = (
    GeneBound(
        name="m",
        low=12.0,
        high=18.0,
        unit="length units (1 unit = 2 mm)",
        reference=float(_BASE_DESIGN["linkage"]["params"]["m"]),
        assumption="assumption: the crank length of the reference design is 15 units; the searched range is a declared "
                   "box around it, not an optimum found anywhere. Same box as O-07 (EXPERIMENTS section 38).",
    ),
    GeneBound(
        name="a",
        low=36.0,
        high=40.0,
        unit="length units (1 unit = 2 mm)",
        reference=float(_BASE_DESIGN["linkage"]["params"]["a"]),
        assumption="assumption: the hip offset of the reference design is 38 units; the searched range is a declared "
                   "box around it. Same box as O-07.",
    ),
    GeneBound(
        name="h",
        low=60.0,
        high=70.0,
        unit="length units (1 unit = 2 mm)",
        reference=float(_BASE_DESIGN["linkage"]["params"]["h"]),
        assumption="assumption: the thigh length of the reference design is 65.7 units; the searched range is a "
                   "declared box around it. Same box as O-07.",
    ),
)

# The two sail genes of W-08.
SAIL_GENES = (
    GeneBound(
        name="sail_area_m2",
        low=0.010,
        high=0.080,
        unit="m2",
        reference=float(_BASE_DESIGN["drive"]["sail"]["area_m2"]),
        assumption="assumption: a printed sail panel on the reference walker (a 0.25 m long, 0.35 kg torso with six "
                   "legs). The lower bound 0.010 m2 is a 10 cm x 10 cm panel, the upper bound 0.080 m2 is 800 cm2, "
                   "a panel of about 0.28 m x 0.28 m that is longer than the torso itself and that the machine would "
                   "have to carry. The reference sail is 0.03 m2 (300 cm2) and W-03's sensitivity table already "
                   "exercised 0.015 m2 and 0.060 m2, so the searched range brackets the values this repository has "
                   "ever run. No printed sail of this walker exists (E3 is empty), so the range is a declared "
                   "plausibility box, not a measurement.",
    ),
    GeneBound(
        name="sail_gear",
        low=4.0,
        high=24.0,
        unit="1 (sail turns per crank turn)",
        reference=float(_BASE_DESIGN["drive"]["sail"]["gear"]),
        assumption="assumption: the sail-to-crank reduction ratio of the reference design is 10. The searched range "
                   "4-24 brackets the 5 and 20 that W-03's sensitivity table already exercised and is meant to cover "
                   "the reduction ratios a hobbyist can realise with a worm or belt reducer between a rotor of about "
                   "0.08 m radius and a 15 mm crank. No catalogue of small gearboxes was consulted and no gear train "
                   "of this walker has ever been built: the range is a declared box, not an optimum found anywhere "
                   "[unverified].",
    ),
)


def _spaces() -> tuple[SailSpace, SailSpace]:
    """The two spaces of the comparison: the fixed sail (no sail genes) and the free sail."""
    fixed = SailSpace(base_design=_BASE_DESIGN, link_genes=LINK_GENES, sail_genes=())
    free = SailSpace(base_design=_BASE_DESIGN, link_genes=LINK_GENES, sail_genes=SAIL_GENES)
    return fixed, free


# ---------------------------------------------------------------------------------------------------------------------
# The declared scenario space (the wind only)
# ---------------------------------------------------------------------------------------------------------------------


def _scenario_space() -> ScenarioSpace:
    """The declared scenario space. Every number is a named assumption (AGENTS.md).

    The space varies the **wind only**: O-07 measured that in the main solver the ground friction is not wired at all
    and that the bump terrain is inert, so those axes would have cost evaluations without adding information. This is
    a narrower claim than section 38's: the numbers below are "robustness against the wind".
    """
    return ScenarioSpace(
        name="w08-wind-only-v1",
        axes=(
            Axis(name="wind_speed_m_s", kind="continuous", low=0.5, high=8.0, unit="m/s",
                 assumption="assumption: the range starts at the reference start wind (about 0.55 m/s under K2, "
                            "EXPERIMENTS section 28 gives 0.49 m/s under MuJoCo) and reaches 8 m/s. Below the start "
                            "wind every design fails for a reason that is not a design, so those scenarios would make "
                            "the CVaR degenerate. The start-wind objective answers the 'not enough wind' question on "
                            "its own. Not a measurement."),
            Axis(name="wind_kind", kind="categorical", values=("constant", "gusts", "profile_turbulent"),
                 assumption="assumption: the three wind models registered in strandbeest_sim.winds (W-04). Which of "
                            "them occurs on a given day is not known."),
            Axis(name="gust_amplitude_m_s", kind="continuous", low=0.5, high=6.0, unit="m/s",
                 assumption="assumption: the gust peak deviation; the winds registry default is 1.0 m/s (not measured)."),
            Axis(name="gust_period_s", kind="continuous", low=2.0, high=15.0, unit="s",
                 assumption="assumption: the winds registry default is 6 s (not measured)."),
            Axis(name="turbulence_intensity", kind="continuous", low=0.05, high=0.30, unit="-",
                 assumption="assumption: the Dryden turbulence intensity I_u; the winds registry default is 0.15 "
                            "(W-04, not measured)."),
            Axis(name="turbulence_seed", kind="integer", low=1, high=8,
                 assumption="assumption: which turbulence realisation is drawn; only the index is defined."),
            Axis(name="yaw_deg", kind="continuous", low=0.0, high=45.0, unit="deg",
                 assumption="assumption: the wind direction stays within 45 deg of the walking direction. Beyond that "
                            "the drive component falls like cos(yaw) and the machine fails for a reason that is the "
                            "same for every design, which would hide the differences between them. A head wind is "
                            "excluded on purpose (it has no drive component at all)."),
        ),
        nominal=Scenario(
            wind_speed_m_s=5.0,
            wind_kind="constant",
            wind_params={"yaw_deg": 0.0},
            terrain_kind="flat",
            terrain_params={},
            friction=1.5,
            slope_deg=0.0,
            label="nominal: constant 5.0 m/s, flat ground, mu=1.5, yaw 0 deg",
        ),
        notes="the declared scenario space of W-08; the sampled set is written to the output file so that every "
              "number below can be traced back to the scenarios that produced it",
    )


def _sample_scenarios(space: ScenarioSpace, n: int, n_gusts: int, seed: int) -> list[Scenario]:
    """The scenario set: stratified over the wind kind, so the gust scenarios are not left to chance.

    With `alpha = 0.1` and `n = 20` the tail mass `alpha * n` is exactly 2, so the CVaR is the mean of the two worst
    outcomes and not the sample minimum (the discrete estimator, see O-07 section 2).
    """
    sampler = ScenarioSampler(space, seed=seed)
    kinds = ("gusts", "constant", "profile_turbulent")
    counts = [n_gusts, (n - n_gusts) // 2]
    counts.append(n - counts[0] - counts[1])
    scenarios: list[Scenario] = []
    for kind, count in zip(kinds, counts):
        for _ in range(count):
            point = sampler.sample_point()
            point["wind_kind"] = kind
            scenarios.append(sampler.scenario_from_point(point))
    return scenarios


# ---------------------------------------------------------------------------------------------------------------------
# The physics (wind driven: the product layer, docs/WIND.md section 2)
# ---------------------------------------------------------------------------------------------------------------------


def _distance_worker(task) -> float:
    """One scenario of one design: the forward distance in metres (higher is better).

    A design whose linkage does not assemble returns -inf ("this candidate does not exist"); a solver crash counts as
    "does not walk" (the same convention as O-07).
    """
    design_doc, scenario, cfg = task

    from strandbeest_common import Design
    from strandbeest_common.linkage import load_spec, solve_pose
    from strandbeest_sim.from_design import scenario_from_design
    from strandbeest_sim.runner import run

    try:
        spec = load_spec(design_doc["linkage"])
        if any(solve_pose(spec, 2 * math.pi * i / ASSEMBLY_PROBES) is None for i in range(ASSEMBLY_PROBES)):
            return DOES_NOT_EXIST
    except Exception:
        return DOES_NOT_EXIST

    overrides = scenario.overrides()
    overrides["drive"] = {"kind": "sail"}
    overrides["run"] = dict(cfg["run"])
    try:
        sc = scenario_from_design(Design(copy.deepcopy(design_doc)), overrides)
        backend = cfg["backend_object"](timestep=cfg["timestep"]) if cfg["backend"] == "k2" else cfg["backend"]
        result = run(sc, backend=backend)
    except Exception:
        return -1.0  # a solver blow-up is a design that does not walk, not a crash of the experiment
    if not len(result.x):
        return -1.0
    return float(result.x[-1] - result.x[0])


def _start_wind_worker(task) -> dict[str, Any]:
    """The start wind of one design: the bracket search of W-03, on the sail drive of this design.

    This is the **verification** measure (the real search); it is far too expensive for the optimisation loop.
    """
    design_doc, cfg = task

    from strandbeest_common import Design
    from strandbeest_common.linkage import load_spec, solve_pose
    from strandbeest_sim.from_design import scenario_from_design
    from strandbeest_sim.runner import run
    from strandbeest_sim.startwind import find_start_wind

    try:
        spec = load_spec(design_doc["linkage"])
        if any(solve_pose(spec, 2 * math.pi * i / ASSEMBLY_PROBES) is None for i in range(ASSEMBLY_PROBES)):
            # the linkage does not assemble: it never starts, and the search is pointless
            return {"lo": 0.0, "hi": None, "estimate": None, "found": False, "trusted": True, "simulations": 0,
                    "runs": [], "note": "the linkage does not assemble"}
    except Exception:
        return {"lo": 0.0, "hi": None, "estimate": None, "found": False, "trusted": True, "simulations": 0,
                "runs": [], "note": "the linkage does not assemble"}

    def attempt(wind: float) -> dict[str, Any]:
        overrides = {
            "drive": {"kind": "sail"},
            "wind": {"kind": "constant", "speed": float(wind), "params": {"yaw_deg": 0.0}},
            "run": {
                "revolutions": 1.0,
                "settle": cfg["settle"],
                "give_up_after": cfg["give_up_after"],
                "max_time": cfg["max_time"],
                "frame_rate": 0,
            },
        }
        try:
            sc = scenario_from_design(Design(copy.deepcopy(design_doc)), overrides)
            backend = cfg["backend_object"](timestep=cfg["timestep"]) if cfg["backend"] == "k2" else cfg["backend"]
            result = run(sc, backend=backend)
        except Exception:
            return {"started": False, "time_s": 0.0, "distance_m": 0.0, "valid": False}
        return {
            "started": not result.stalled,
            "time_s": float(result.t[-1]) if len(result.t) else 0.0,
            "distance_m": float(result.x[-1] - result.x[0]) if len(result.x) else 0.0,
            "valid": bool(result.metrics.get("max_loop_violation", 0.0) < 0.0017),
        }

    result = find_start_wind(
        attempt,
        guess=cfg["start_wind_guess"],
        rel_tol=cfg["rel_tol"],
        w_min=cfg["w_min"],
        w_max=cfg["w_max"],
    )
    return {
        "lo": float(result.lo),
        "hi": float(result.hi) if math.isfinite(result.hi) else None,
        "estimate": float(result.estimate) if result.found else None,
        "found": bool(result.found),
        "trusted": bool(result.trusted),
        "simulations": len(result.runs),
        "runs": result.runs,
    }


def _proxy_start_wind(design_doc: dict[str, Any]) -> dict[str, Any]:
    """The cheap start-wind proxy: the quasi-static threshold of the virtual dynamometer (EXPERIMENTS section 32).

    The virtual dynamometer measures the load torque curve T(theta) and the aero factor of the sail; the quasi-static
    threshold is

        v* = sqrt( max(0, peak_load_torque) / aero_factor ),   aero_factor = gear * 0.5 * rho * Cd * A * r

    which is what the sail has to overcome at standstill. It costs one slow-constant-speed analysis, not a search, so
    it can sit inside the optimisation loop. **Measured cost: 0.56 s per candidate** (the 180-sample torque sweep on this
    machine), not the 15 ms an earlier draft of this comment claimed; it is still three orders of magnitude cheaper
    than the real start-wind search (about 390 s per design), which is why only the latter verifies the final designs.

    **One correction.** The dynamometer weighs the machine with `walker.mass`, which for a design that declares a
    torso mass is the *schema default of 50 kg* (the scenario's `body_mass` is what the solvers actually use). The
    peak load torque is proportional to the weight, so it is rescaled here to the design's torso mass -- the mass
    EXPERIMENTS section 32 used (its published peak of 2.58 mN*m is reproduced to 0.6 %). The rescaling assumes the
    pin friction is zero (the default); with a non-zero pin friction it would be approximate, because that term is
    mass independent. The factor is the same for every candidate (the torso mass does not depend on the genes), so
    the ranking of the candidates is not affected by it.
    """
    from strandbeest_common import Design
    from strandbeest_common.linkage import load_spec, solve_pose
    from strandbeest_sim.config import sim_config
    from strandbeest_sim.dynamometer import virtual_dynamometer
    from strandbeest_sim.from_design import scenario_from_design

    design = Design(copy.deepcopy(design_doc))
    # A linkage that does not assemble has no load torque curve: the candidate does not exist at all (the same
    # convention as the distance worker).
    try:
        spec = load_spec(design_doc["linkage"])
        if any(solve_pose(spec, 2 * math.pi * i / ASSEMBLY_PROBES) is None for i in range(ASSEMBLY_PROBES)):
            return {"threshold_m_s": math.inf, "assembles": False, "peak_load_torque_nm": 0.0,
                    "peak_load_torque_as_reported_nm": 0.0, "aero_factor": 0.0, "mass_used_kg": 0.0,
                    "mass_reference_kg": 0.0, "sail_parameters": {}}
    except Exception:
        return {"threshold_m_s": math.inf, "assembles": False, "peak_load_torque_nm": 0.0,
                "peak_load_torque_as_reported_nm": 0.0, "aero_factor": 0.0, "mass_used_kg": 0.0,
                "mass_reference_kg": 0.0, "sail_parameters": {}}

    walker = sim_config(scenario_from_design(design)).walker
    mass_used = float(walker.mass)
    mass_reference = float(walker.body_mass) if walker.body_mass is not None else mass_used
    try:
        result = virtual_dynamometer(design, samples=180, slope_deg=0.0)
    except Exception:
        return {"threshold_m_s": math.inf, "assembles": False, "peak_load_torque_nm": 0.0,
                "peak_load_torque_as_reported_nm": 0.0, "aero_factor": 0.0, "mass_used_kg": mass_used,
                "mass_reference_kg": mass_reference, "sail_parameters": {}}
    peak = float(result["peak_torque"]) * (mass_reference / mass_used)
    aero = float(result["sail_parameters"]["aero_factor"])
    threshold = math.sqrt(max(0.0, peak) / aero) if aero > 0 else float("inf")
    return {
        "threshold_m_s": float(threshold),
        "assembles": True,
        "peak_load_torque_nm": float(peak),
        "peak_load_torque_as_reported_nm": float(result["peak_torque"]),
        "aero_factor": float(aero),
        "mass_used_kg": mass_used,
        "mass_reference_kg": mass_reference,
        "sail_parameters": dict(result["sail_parameters"]),
    }


def _pool_start_wind(pool, cfg: dict, space: SailSpace, genomes: Sequence[Sequence[float]]) -> list[dict[str, Any]]:
    """The start wind of several designs in one parallel sweep (the search is the expensive part)."""
    tasks = [(space.to_design(g), cfg) for g in genomes]
    if pool is None:
        return [_start_wind_worker(t) for t in tasks]
    return list(pool.map(_start_wind_worker, tasks, chunksize=1))


class SailEvaluator:
    """The injected physics: the forward distance of a genome in a scenario.

    It offers the batch protocol of `strandbeest_opt.robust`, so the scenarios of one candidate run side by side.
    """

    def __init__(self, pool, cfg: dict, space: SailSpace) -> None:
        self._pool = pool
        self._cfg = cfg
        self._space = space
        self.evaluations = 0

    def __call__(self, genome: Sequence[float], scenario: Scenario) -> float:
        return self.evaluate_batch(genome, [scenario])[0]

    def evaluate_batch(self, genome: Sequence[float], scenarios: Sequence[Scenario]) -> list[float]:
        design_doc = self._space.to_design(genome)
        tasks = [(design_doc, sc, self._cfg) for sc in scenarios]
        if self._pool is None:
            results = [_distance_worker(t) for t in tasks]
        else:
            results = list(self._pool.map(_distance_worker, tasks, chunksize=1))
        self.evaluations += len(tasks)
        return [float(r) for r in results]


# ---------------------------------------------------------------------------------------------------------------------
# The optimisation
# ---------------------------------------------------------------------------------------------------------------------


def _population_scores(
    space: SailSpace,
    population: Sequence[Sequence[float]],
    scenarios: Sequence[Scenario],
    pool,
    cfg: dict,
    objective: SailObjective,
) -> tuple[list[float], list[dict[str, Any]]]:
    """Evaluate a whole CMA-ES population in one parallel sweep.

    `population` is given in the unit cube (what CMA-ES asks for); it is mapped back onto the physical genes here.
    The start-wind term is the cheap quasi-static proxy (computed in this process, 0.56 s per candidate, measured); the
    physics that costs is the scenario set, and the scenarios of a whole population go into the pool at once.
    """
    genomes = [space.from_unit(x) for x in population]
    design_docs = [space.to_design(g) for g in genomes]
    proxies = [_proxy_start_wind(doc) for doc in design_docs]
    tasks = [(doc, scenario, cfg) for doc in design_docs for scenario in scenarios]
    if pool is None:
        results = [_distance_worker(t) for t in tasks]
    else:
        results = list(pool.map(_distance_worker, tasks, chunksize=1))

    # The loop's evaluations do not pass through `SailEvaluator.evaluate_batch`, so the evaluation counter is bumped
    # here: the budget report has to count **every** physics evaluation, not only the ones of the final table.
    counter = getattr(objective.evaluate, "evaluations", None)
    if isinstance(counter, int):
        objective.evaluate.evaluations += len(tasks)

    scores: list[float] = []
    details: list[dict[str, Any]] = []
    index = 0
    for proxy in proxies:
        outcomes = results[index: index + len(scenarios)]
        index += len(scenarios)
        scores.append(objective.score_from_parts(proxy["threshold_m_s"], outcomes))
        details.append({"proxy": proxy, "outcomes": list(outcomes)})
    return scores, details


def _run_cma(
    space: SailSpace,
    scenarios: Sequence[Scenario],
    pool,
    cfg: dict,
    objective: SailObjective,
    args,
) -> dict[str, Any]:
    """One CMA-ES run over the unit cube of the space (the same optimiser, seed, budget and population for every run)."""
    x0 = space.to_unit(space.reference_genome)
    dimension = space.dimension
    opt = CmaEs(x0, args.sigma0, ([0.0] * dimension, [1.0] * dimension), seed=args.seed, popsize=args.popsize)
    history: list[float] = []
    evaluations = 0
    best_details: dict[str, Any] | None = None
    best_score = -math.inf
    while not opt.stop() and evaluations < args.evals:
        population = opt.ask()
        scores, details = _population_scores(space, population, scenarios, pool, cfg, objective)
        for index, score in enumerate(scores):
            if score > best_score:
                best_score = score
                best_details = details[index]
        opt.tell(population, scores)
        evaluations += len(population)
        history.append(float(opt.best_f))
    genome = space.from_unit(opt.best)
    return {
        "objective": objective.weights.to_dict(),
        "genome": [float(v) for v in genome],
        "score": float(opt.best_f),
        "candidate_evaluations": int(opt.evals),
        "generations": len(history),
        "history": history,
        "best_details": best_details,
    }


# ---------------------------------------------------------------------------------------------------------------------
# The experiment
# ---------------------------------------------------------------------------------------------------------------------


def _clean(obj):
    """Replace the non-finite floats (a candidate that does not exist) by null, so the file is strict JSON."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _scenario_from_dict(space: ScenarioSpace, data: dict) -> Scenario:
    """Rebuild a scenario from the JSON form the adversarial search returns."""
    wind = data.get("wind", {})
    terrain = data.get("terrain", {})
    params = dict(wind.get("params") or {})
    point = {
        "wind_speed_m_s": wind.get("speed_m_s", 0.0),
        "wind_kind": wind.get("kind", "constant"),
        "yaw_deg": float(params.get("yaw_deg", 0.0)),
        "friction": float(terrain.get("friction", 1.5)),
        "slope_deg": float(terrain.get("slope_deg", 0.0)),
    }
    if wind.get("kind") == "gusts":
        point["gust_amplitude_m_s"] = float(params.get("amplitude", 1.0))
        point["gust_period_s"] = float(params.get("period", 6.0))
    return scenario_from_point(point, space.nominal)


def _row(name: str, kind: str, space: SailSpace, genome: Sequence[float], detail: dict[str, Any],
         nominal_distance: float, scenarios: Sequence[Scenario], alpha: float) -> dict[str, Any]:
    """One row of the final table."""
    proxy = detail["proxy"]
    outcomes = list(detail["outcomes"])
    return {
        "name": name,
        "space": kind,
        "sail": space.sail_of(genome).to_dict(),
        "genome": [float(v) for v in genome],
        "start_wind_proxy_m_s": float(proxy["threshold_m_s"]),
        "peak_load_torque_nm": float(proxy["peak_load_torque_nm"]),
        "aero_factor": float(proxy["aero_factor"]),
        "cvar_m": cvar_lower(outcomes, alpha),
        "worst_case_m": min(outcomes),
        "mean_m": sum(outcomes) / len(outcomes),
        "nominal_distance_m": float(nominal_distance),
        "scenario_values": {sc.describe(): float(v) for sc, v in zip(scenarios, outcomes)},
    }


def _worst_gust_only(args) -> None:
    """The supplementary measurement: **every** design of the final table on the two worst-gust sequences.

    The main run compares the nominally optimal design with the design of the default robust objective. With a small
    budget those two can turn out to be the *same* design, which makes that comparison vacuous; this mode measures all
    the designs of the table (every weighting of both spaces) on the same two sequences, so the comparison has content.

    It reads the output file of the main run (the designs and the two worst-gust sequences are already in it) and
    merges the numbers back into that file, under `worst_gust_all_designs`. No re-search, no new budget.
    """
    from strandbeest_sim.backends.k2_backend import K2Backend

    out = Path(args.out)
    data = json.loads(out.read_text())
    fixed_space, free_space = _spaces()
    space = _scenario_space()
    cfg = {
        "backend": "k2",
        "backend_object": K2Backend,
        "timestep": args.timestep,
        "settle": args.settle,
        "max_time": args.max_time,
        "give_up_after": args.give_up,
        "rel_tol": args.rel_tol,
        "start_wind_guess": 0.5,
        "w_min": 0.02,
        "w_max": 30.0,
        "run": {
            "revolutions": 10.0,
            "settle": args.settle,
            "max_time": args.window,
            "frame_rate": 0,
            "give_up_after": args.window * 0.6,
        },
    }

    designs: list[tuple[str, SailSpace, list[float]]] = []
    for row in data.get("table", []):
        target = free_space if row.get("space") == "free" else fixed_space
        designs.append((row["name"], target, list(row["genome"])))

    sequences: dict[str, Scenario] = {}
    for key, source in (
        ("sampled_set", (data.get("worst_gust_sequence") or {}).get("scenario")),
        ("adversarial", (data.get("adversarial_gust_comparison") or {}).get("scenario")),
    ):
        if source:
            sequences[key] = _scenario_from_dict(space, source)
    if not sequences:
        raise SystemExit("the output file has no worst-gust sequence to measure on")

    t0 = time.time()
    workers = max(1, min(args.workers, os.cpu_count() or 1))
    sequences_out: dict[str, Any] = {}
    with mp.Pool(processes=workers) as pool:
        for key, scenario in sequences.items():
            tasks = [(target.to_design(genome), scenario, cfg) for _, target, genome in designs]
            results = list(pool.map(_distance_worker, tasks, chunksize=1))
            values = {name: float(value) for (name, _, _), value in zip(designs, results)}
            nominal = values.get("free_sail_nominal")

            def delta(name: str) -> float | None:
                if nominal is None or name not in values:
                    return None
                return float(values[name] - nominal)

            sequences_out[key] = {
                "scenario": scenario.to_dict(),
                "scenario_label": scenario.describe(),
                "distances_m": values,
                "minus_free_sail_nominal_m": {name: delta(name) for name in values},
                "free_sail_robust_minus_nominal_m": delta("free_sail_robust"),
                "free_sail_robust_only_minus_nominal_m": delta("free_sail_robust_only"),
                "fixed_sail_robust_minus_nominal_m": delta("fixed_sail_robust"),
            }
            print(
                f"[w08] {key:12s} '{scenario.describe()}': "
                + ", ".join(f"{name} {value:+.6f} m" for name, value in values.items()),
                flush=True,
            )

    data["worst_gust_all_designs"] = {
        "how": "every design of the final table on the two worst-gust sequences of the main run (the gust scenario of "
               "the sampled set in which the nominally optimal design walks least far, and the worst sequence the "
               "adversarial search found for it); no re-search, the designs are the ones of the main run",
        "physics": {"backend": "k2", "timestep_s": args.timestep, "window_s": args.window, "drive": "sail"},
        "sequences": sequences_out,
        "wall_time_s": time.time() - t0,
    }
    out.write_text(json.dumps(_clean(data), indent=1, default=float) + "\n")
    print(f"[w08] merged the supplementary measurement into {out.name} in {time.time() - t0:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--alpha", type=float, default=0.1, help="tail probability of the CVaR (WIND.md: 0.1 = worst 10 %)")
    ap.add_argument("--scenarios", type=int, default=20, help="size of the sampled scenario set")
    ap.add_argument("--gusts", type=int, default=8, help="how many of the sampled scenarios are gust scenarios")
    ap.add_argument("--evals", type=int, default=120, help="candidate evaluations per CMA-ES run")
    ap.add_argument("--popsize", type=int, default=12)
    ap.add_argument("--sigma0", type=float, default=0.15, help="initial sigma on the unit cube")
    ap.add_argument("--workers", type=int, default=8, help="parallel simulator processes")
    ap.add_argument("--backend", default="k2", choices=("k2", "mujoco"))
    ap.add_argument("--timestep", type=float, default=1e-3, help="solver time step (s) of the reported table")
    ap.add_argument("--loop-timestep", type=float, default=2e-3,
                    help="solver time step (s) of the optimisation loop. The loop evaluates hundreds of candidates and "
                         "the scenario set is the expensive part, so the loop runs on a coarser step; the reported "
                         "table is re-evaluated on the fine step, and the difference is measured (the step check)")
    ap.add_argument("--window", type=float, default=2.5, help="driving window (s); the outcome is the distance in it")
    ap.add_argument("--settle", type=float, default=0.2)
    ap.add_argument("--max-time", type=float, default=40.0, help="simulated time one start attempt may take (s)")
    ap.add_argument("--give-up", type=float, default=10.0, help="simulated time after which a stalled crank gives up (s)")
    ap.add_argument("--rel-tol", type=float, default=0.05, help="relative tolerance of the start-wind bracket")
    ap.add_argument("--random-pool", type=int, default=12, help="scenarios drawn for the adversarial gust search")
    ap.add_argument("--refine-budget", type=int, default=24, help="scenario evaluations of the adversarial refinement")
    ap.add_argument("--no-cross-check", action="store_true", help="skip the MuJoCo cross-check of the final table")
    ap.add_argument("--worst-gust-only", action="store_true",
                    help="supplementary measurement: evaluate **every** design of an existing output file on the two "
                         "worst-gust sequences and merge the numbers back into that file (no re-search)")
    ap.add_argument("--out", default=str(ROOT / "experiments/sail-gene-optimization.json"))
    args = ap.parse_args()

    if args.worst_gust_only:
        _worst_gust_only(args)
        return

    from strandbeest_sim.backends.k2_backend import K2Backend

    cfg = {
        "backend": args.backend,
        "backend_object": K2Backend,
        "timestep": args.loop_timestep,
        "settle": args.settle,
        "max_time": args.max_time,
        "give_up_after": args.give_up,
        "rel_tol": args.rel_tol,
        "start_wind_guess": 0.5,
        "w_min": 0.02,
        "w_max": 30.0,
        "run": {
            "revolutions": 10.0,
            "settle": args.settle,
            "max_time": args.window,
            "frame_rate": 0,
            "give_up_after": args.window * 0.6,
        },
    }
    # The fine configuration: the reported table is evaluated on the step O-07 used, the loop on a coarser one.
    fine_cfg = dict(cfg)
    fine_cfg["timestep"] = args.timestep

    fixed_space, free_space = _spaces()
    space = _scenario_space()
    scenarios = _sample_scenarios(space, args.scenarios, args.gusts, args.seed)

    t_start = time.time()
    workers = max(1, min(args.workers, os.cpu_count() or 1))
    print(f"[w08] backend={args.backend} timestep={args.timestep} window={args.window}s workers={workers}", flush=True)
    print(f"[w08] sampled {len(scenarios)} scenarios (seed {args.seed}, {args.gusts} of them gusts)", flush=True)

    with mp.Pool(processes=workers) as pool:
        evaluators = {
            "fixed": SailEvaluator(pool, cfg, fixed_space),
            "free": SailEvaluator(pool, cfg, free_space),
        }

        # ------------------------------------------------------------------ the anchors of the objective
        reference_genome = fixed_space.reference_genome
        reference_proxy = _proxy_start_wind(fixed_space.to_design(reference_genome))
        reference_outcomes = evaluators["fixed"].evaluate_batch(reference_genome, scenarios)
        reference_nominal = evaluators["fixed"].evaluate_batch(reference_genome, [space.nominal])[0]
        anchors = Anchors(
            start_wind_m_s=reference_proxy["threshold_m_s"],
            cvar_m=cvar_lower(reference_outcomes, args.alpha),
            distance_m=reference_nominal,
        )
        print(
            f"[w08] anchors (the reference design): proxy start wind {anchors.start_wind_m_s:.4f} m/s, "
            f"CVaR {anchors.cvar_m:+.6f} m, nominal distance {reference_nominal:+.6f} m",
            flush=True,
        )

        # ------------------------------------------------------------------ the runs
        # The weighting grid: the free sail at five weightings, the fixed sail at the two ends. Same optimiser,
        # same seed, same budget, same population for every run.
        plan = [
            ("free", 0.0, "free_sail_nominal"),
            ("free", 0.25, "free_sail_w25"),
            ("free", 0.5, "free_sail_robust"),
            ("free", 0.75, "free_sail_w75"),
            ("free", 1.0, "free_sail_robust_only"),
            ("fixed", 0.0, "fixed_sail_nominal"),
            ("fixed", 0.5, "fixed_sail_robust"),
        ]
        runs: dict[str, Any] = {}
        designs: dict[str, list[float]] = {"reference": list(reference_genome)}
        details: dict[str, dict[str, Any]] = {
            "reference": {"proxy": reference_proxy, "outcomes": list(reference_outcomes)}
        }
        for kind, robust, name in plan:
            target_space = free_space if kind == "free" else fixed_space
            weights = ObjectiveWeights.of_robust(robust)

            def start_wind_proxy(genome, _space=target_space):
                """The cheap start-wind term of the objective (the quasi-static threshold)."""
                return _proxy_start_wind(_space.to_design(genome))["threshold_m_s"]

            objective = SailObjective(
                target_space,
                scenarios,
                evaluators[kind],
                start_wind_proxy,
                alpha=args.alpha,
                weights=weights,
                anchors=anchors,
            )
            t0 = time.time()
            run = _run_cma(target_space, scenarios, pool, cfg, objective, args)
            run["space"] = kind
            run["name"] = name
            run["wall_time_s"] = time.time() - t0
            runs[name] = run
            designs[name] = run["genome"]
            details[name] = run.pop("best_details") or {"proxy": {}, "outcomes": []}
            print(
                f"[w08] {name:20s} (space={kind:5s} w_robust={robust:.2f}) score {run['score']:+.4f} "
                f"candidates {run['candidate_evaluations']} generations {run['generations']} "
                f"wall {run['wall_time_s']:.0f}s",
                flush=True,
            )

        # ------------------------------------------------------------------ the verification: the real start wind
        # The real search (W-03) on the final designs and on the reference: this is the measure the card asks for.
        fine_designs: list[tuple[str, SailSpace, list[float]]] = []
        for name, genome in designs.items():
            kind = "free" if name.startswith("free") else "fixed"
            fine_designs.append((name, free_space if kind == "free" else fixed_space, list(genome)))
        measured: dict[str, dict[str, Any]] = {}
        for kind_space in (fixed_space, free_space):
            group = [(n, g) for n, s, g in fine_designs if s is kind_space]
            if not group:
                continue
            results = _pool_start_wind(pool, fine_cfg, kind_space, [g for _, g in group])
            for (name, _), result in zip(group, results):
                measured[name] = result
        print(
            "[w08] the real start-wind search on the final designs: "
            + ", ".join(
                f"{n} {measured[n]['estimate']:.4f} m/s" if measured[n].get("estimate") is not None else f"{n} n/a"
                for n, _, _ in fine_designs
            ),
            flush=True,
        )

        # ------------------------------------------------------------------ the final table
        # The reported table is evaluated on the fine step (the step O-07 used); the loop ran on the coarser one.
        fine_evaluators = {
            "fixed": SailEvaluator(pool, fine_cfg, fixed_space),
            "free": SailEvaluator(pool, fine_cfg, free_space),
        }
        table = []
        for name, genome in designs.items():
            kind = "free" if name.startswith("free") else "fixed"
            target_space = free_space if kind == "free" else fixed_space
            evaluator = fine_evaluators[kind]
            outcomes = evaluator.evaluate_batch(genome, scenarios)
            nominal_distance = evaluator.evaluate_batch(genome, [space.nominal])[0]
            detail = {"proxy": details[name]["proxy"], "outcomes": outcomes}
            row = _row(name, kind, target_space, genome, detail, nominal_distance, scenarios, args.alpha)
            search = measured.get(name, {})
            row["start_wind_measured_m_s"] = float(search["estimate"]) if search.get("estimate") is not None else None
            row["start_wind_measured_interval"] = [float(search["lo"]), search.get("hi")]
            row["start_wind_search_simulations"] = int(search.get("simulations", 0))
            row["start_wind_trusted"] = bool(search.get("trusted", True))
            table.append(row)
            print(
                f"[w08] {name:20s} start wind {row['start_wind_measured_m_s']} m/s "
                f"(proxy {row['start_wind_proxy_m_s']:.4f})  CVaR {row['cvar_m']:+.6f} m  "
                f"nominal distance {row['nominal_distance_m']:+.6f} m  sail {row['sail']}",
                flush=True,
            )

        # the step check of the scenario runs (a check of the discretisation, not a validation)
        step_check = {
            "loop_step_s": args.loop_timestep,
            "reported_step_s": args.timestep,
            "reference_nominal_distance_loop_step_m": float(reference_nominal),
            "note": "the reference design at the nominal scenario, on the two grids; EXPERIMENTS section 38 measured "
                    "the same kind of difference for the distance (-2.3 % at 2e-3 against 1e-3)",
        }

        # ------------------------------------------------------------------ the proxy against the real search
        proxy_check = []
        for row in table:
            measured_value = row["start_wind_measured_m_s"]
            proxy_value = row["start_wind_proxy_m_s"]
            proxy_check.append(
                {
                    "name": row["name"],
                    "proxy_m_s": proxy_value,
                    "measured_m_s": measured_value,
                    "measured_over_proxy": (measured_value / proxy_value) if measured_value else None,
                    "proxy_over_measured": (proxy_value / measured_value) if measured_value else None,
                }
            )
        pairs = [(c["proxy_m_s"], c["measured_m_s"]) for c in proxy_check if c["measured_m_s"]]
        rho = _spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) > 2 else None
        proxy_check_summary = {
            "designs": proxy_check,
            "spearman_rho_proxy_vs_measured": rho,
            "mean_measured_over_proxy": (
                sum(c["measured_over_proxy"] for c in proxy_check if c["measured_over_proxy"]) / len(pairs)
                if pairs else None
            ),
            "note": "the proxy is the quasi-static threshold of the virtual dynamometer (EXPERIMENTS section 32); "
                    "the measured column is the W-03 search. A rho near 1 means the cheap tier ranks the designs the "
                    "same way as the expensive one; it is a check, not a validation",
        }
        print(
            f"[w08] proxy vs the real search: Spearman rho = {rho}, "
            f"the measured start wind is {proxy_check_summary['mean_measured_over_proxy']:.3f}x the proxy",
            flush=True,
        )

        # ------------------------------------------------------------------ the worst gust sequence
        by_name = {row["name"]: row for row in table}
        gust_scenarios = [sc for sc in scenarios if sc.wind_kind == "gusts"]
        worst_gust = None
        if gust_scenarios:
            values = by_name["free_sail_nominal"]["scenario_values"]
            worst_gust = min(gust_scenarios, key=lambda sc: values.get(sc.describe(), math.inf))
        worst_gust_comparison = None
        if worst_gust is not None:
            nominal_value = fine_evaluators["free"].evaluate_batch(designs["free_sail_nominal"], [worst_gust])[0]
            robust_value = fine_evaluators["free"].evaluate_batch(designs["free_sail_robust"], [worst_gust])[0]
            fixed_value = fine_evaluators["fixed"].evaluate_batch(designs["fixed_sail_robust"], [worst_gust])[0]
            worst_gust_comparison = {
                "scenario": worst_gust.to_dict(),
                "scenario_label": worst_gust.describe(),
                "how": "the gust scenario of the sampled set in which the nominally optimal design walks least far",
                "free_sail_nominal_m": float(nominal_value),
                "free_sail_robust_m": float(robust_value),
                "fixed_sail_robust_m": float(fixed_value),
                "robust_minus_nominal_m": float(robust_value - nominal_value),
                "robust_beats_nominal": bool(robust_value >= nominal_value),
            }
            print(
                f"[w08] worst gust sequence '{worst_gust.describe()}': nominal {nominal_value:+.6f} m, "
                f"robust {robust_value:+.6f} m (diff {robust_value - nominal_value:+.6f} m)",
                flush=True,
            )

        # ------------------------------------------------------------------ the adversarial gust search
        gust_space = ScenarioSpace(
            name="w08-gust-only-v1",
            axes=(
                Axis(name="wind_kind", kind="categorical", values=("gusts",),
                     assumption="assumption: the gust-only sub-space of the search; the card asks about the worst gust "
                                "sequence, so the wind kind is fixed to the gust model of strandbeest_sim.winds"),
                Axis(name="wind_speed_m_s", kind="continuous", low=0.5, high=8.0, unit="m/s",
                     assumption="assumption: the wind speed of the gust sequence, from the reference start wind upwards"),
                Axis(name="gust_amplitude_m_s", kind="continuous", low=0.5, high=6.0, unit="m/s",
                     assumption="assumption: the gust peak deviation (the winds registry default is 1.0 m/s, not measured)"),
                Axis(name="gust_period_s", kind="continuous", low=2.0, high=15.0, unit="s",
                     assumption="assumption: the gust period (the winds registry default is 6 s, not measured)"),
                Axis(name="yaw_deg", kind="continuous", low=0.0, high=45.0, unit="deg",
                     assumption="assumption: the wind direction stays within 45 deg of the walking direction"),
            ),
            nominal=space.nominal,
            notes="the gust-only sub-space of the adversarial search: the card asks about the worst gust sequence",
        )
        adversarial = {}
        for name in ("free_sail_nominal", "free_sail_robust"):
            evaluator = fine_evaluators["free"]
            t0 = time.time()
            result = adversarial_search(
                gust_space,
                designs[name],
                evaluator,
                seed=args.seed,
                n_random=args.random_pool,
                n_refine=args.refine_budget,
            )
            adversarial[name] = result.to_dict()
            print(
                f"[w08] adversarial gust [{name}]: worst {result.value:+.6f} m in '{result.scenario.describe()}' "
                f"(pool {result.random_value:+.6f} m, {result.evaluations} evaluations, {time.time() - t0:.0f}s)",
                flush=True,
            )
        adversarial_comparison = None
        if adversarial:
            scenario = _scenario_from_dict(gust_space, adversarial["free_sail_nominal"]["scenario"])
            nominal_value = fine_evaluators["free"].evaluate_batch(designs["free_sail_nominal"], [scenario])[0]
            robust_value = fine_evaluators["free"].evaluate_batch(designs["free_sail_robust"], [scenario])[0]
            fixed_value = fine_evaluators["fixed"].evaluate_batch(designs["fixed_sail_robust"], [scenario])[0]
            adversarial_comparison = {
                "scenario": scenario.to_dict(),
                "scenario_label": scenario.describe(),
                "how": "the worst gust sequence the adversarial search found for the nominally optimal design",
                "free_sail_nominal_m": float(nominal_value),
                "free_sail_robust_m": float(robust_value),
                "fixed_sail_robust_m": float(fixed_value),
                "robust_minus_nominal_m": float(robust_value - nominal_value),
                "robust_beats_nominal": bool(robust_value >= nominal_value),
            }
            print(
                f"[w08] adversarial worst gust '{scenario.describe()}': nominal {nominal_value:+.6f} m, "
                f"robust {robust_value:+.6f} m (diff {robust_value - nominal_value:+.6f} m)",
                flush=True,
            )

        # ------------------------------------------------------------------ the weighting sensitivity
        weighting_table = []
        for name, run in runs.items():
            row = by_name[name]
            weighting_table.append(
                {
                    "name": name,
                    "space": run["space"],
                    "w_robust": run["objective"]["robust"],
                    "w_start": run["objective"]["start"],
                    "start_wind_proxy_m_s": row["start_wind_proxy_m_s"],
                    "start_wind_measured_m_s": row["start_wind_measured_m_s"],
                    "cvar_m": row["cvar_m"],
                    "nominal_distance_m": row["nominal_distance_m"],
                    "sail": row["sail"],
                    "score": run["score"],
                }
            )
        weighting_table.sort(key=lambda r: (r["space"], r["w_robust"]))

        # ------------------------------------------------------------------ the MuJoCo cross-check
        cross_check = None
        if not args.no_cross_check and args.backend == "k2":
            mujoco_cfg = dict(fine_cfg)
            mujoco_cfg["backend"] = "mujoco"
            mujoco_evaluators = {
                "fixed": SailEvaluator(pool, mujoco_cfg, fixed_space),
                "free": SailEvaluator(pool, mujoco_cfg, free_space),
            }
            cross_names = ("reference", "fixed_sail_robust", "free_sail_nominal", "free_sail_robust")
            cross_check = {}
            for name in cross_names:
                kind = "free" if name.startswith("free") else "fixed"
                evaluator = mujoco_evaluators[kind]
                outcomes = evaluator.evaluate_batch(designs[name], scenarios)
                nominal_distance = evaluator.evaluate_batch(designs[name], [space.nominal])[0]
                cross_check[name] = {
                    "cvar_m": cvar_lower(outcomes, args.alpha),
                    "nominal_distance_m": float(nominal_distance),
                }
                print(
                    f"[w08] mujoco cross-check {name:20s} CVaR {cross_check[name]['cvar_m']:+.6f} m  "
                    f"nominal {nominal_distance:+.6f} m",
                    flush=True,
                )
            # the real start wind under the second solver (the same W-03 search, MuJoCo instead of K2). MuJoCo is
            # slow, so this is a spot check on two designs only.
            spot = ("reference", "free_sail_robust")
            for kind_space, group in (
                (fixed_space, [(n, g) for n, s, g in fine_designs if s is fixed_space and n in spot]),
                (free_space, [(n, g) for n, s, g in fine_designs if s is free_space and n in spot]),
            ):
                if not group:
                    continue
                results = _pool_start_wind(pool, mujoco_cfg, kind_space, [g for _, g in group])
                for (name, _), result in zip(group, results):
                    cross_check[name]["start_wind_measured_m_s"] = (
                        float(result["estimate"]) if result.get("estimate") is not None else None
                    )
                    cross_check[name]["start_wind_interval"] = [float(result["lo"]), result.get("hi")]
                    print(
                        f"[w08] mujoco start wind {name:20s} {cross_check[name]['start_wind_measured_m_s']} m/s",
                        flush=True,
                    )
            if worst_gust is not None:
                entry = {
                    "label": worst_gust.describe(),
                    "free_sail_nominal_m": float(mujoco_evaluators["free"].evaluate_batch(designs["free_sail_nominal"], [worst_gust])[0]),
                    "free_sail_robust_m": float(mujoco_evaluators["free"].evaluate_batch(designs["free_sail_robust"], [worst_gust])[0]),
                    "fixed_sail_robust_m": float(mujoco_evaluators["fixed"].evaluate_batch(designs["fixed_sail_robust"], [worst_gust])[0]),
                }
                entry["robust_minus_nominal_m"] = entry["free_sail_robust_m"] - entry["free_sail_nominal_m"]
                entry["robust_beats_nominal"] = bool(entry["free_sail_robust_m"] >= entry["free_sail_nominal_m"])
                cross_check["worst_gust_sequence"] = entry
                print(
                    f"[w08] mujoco worst gust '{worst_gust.describe()}': nominal {entry['free_sail_nominal_m']:+.6f} m, "
                    f"robust {entry['free_sail_robust_m']:+.6f} m",
                    flush=True,
                )
            cross_check["evaluations"] = {
                "fixed": mujoco_evaluators["fixed"].evaluations,
                "free": mujoco_evaluators["free"].evaluations,
            }

    # ------------------------------------------------------------------ the verdict
    by_name = {row["name"]: row for row in table}
    fixed_row = by_name["fixed_sail_robust"]
    free_row = by_name["free_sail_robust"]
    verdict = {
        "criterion_1_side_by_side": {
            "question": "the free sail (the area and the gear as genes) against the fixed sail, same optimiser, same "
                        "budget, same seed, same evaluation count",
            "fixed_sail": {
                "start_wind_measured_m_s": fixed_row["start_wind_measured_m_s"],
                "start_wind_proxy_m_s": fixed_row["start_wind_proxy_m_s"],
                "cvar_m": fixed_row["cvar_m"],
                "nominal_distance_m": fixed_row["nominal_distance_m"],
                "sail": fixed_row["sail"],
            },
            "free_sail": {
                "start_wind_measured_m_s": free_row["start_wind_measured_m_s"],
                "start_wind_proxy_m_s": free_row["start_wind_proxy_m_s"],
                "cvar_m": free_row["cvar_m"],
                "nominal_distance_m": free_row["nominal_distance_m"],
                "sail": free_row["sail"],
            },
            "start_wind_ratio_free_over_fixed": (
                free_row["start_wind_measured_m_s"] / fixed_row["start_wind_measured_m_s"]
                if fixed_row["start_wind_measured_m_s"] and free_row["start_wind_measured_m_s"]
                else None
            ),
            "cvar_difference_m": free_row["cvar_m"] - fixed_row["cvar_m"],
            "nominal_distance_difference_m": free_row["nominal_distance_m"] - fixed_row["nominal_distance_m"],
        },
        "criterion_2_worst_gust_sequence": {
            "question": "in the worst gust sequence, does the design of the robust objective do no worse than the "
                        "nominally optimal design?",
            "in_the_sampled_set": worst_gust_comparison,
            "in_the_adversarial_search": adversarial_comparison,
        },
        "proxy_check": proxy_check_summary,
        "note": "all the numbers are model output (K2, or MuJoCo for the cross-check), not a prediction and not a "
                "measurement; the search is budget-limited and no convergence is claimed",
    }

    report = {
        "card": "W-08",
        "generated_by": "packages/opt/scripts/sail_gene_run.py",
        "seed": args.seed,
        "alpha": args.alpha,
        "gene_space": {
            "fixed_sail": fixed_space.to_dict(),
            "free_sail": free_space.to_dict(),
            "link_genes": [g.to_dict() for g in LINK_GENES],
            "sail_genes": [g.to_dict() for g in SAIL_GENES],
            "note": "the genome is [link values..., sail values...]; the optimiser works on the unit cube so that one "
                    "sigma means the same thing for a 0.08 m2 sail and a 70 mm link",
        },
        "scenario_space": space.to_dict(),
        "sampled_scenarios": [s.to_dict() for s in scenarios],
        "anchors": anchors.to_dict(),
        "physics": {
            "backend": args.backend,
            "timestep_s": args.timestep,
            "drive": "sail (wind driven: the product layer, docs/WIND.md section 2)",
            "run": cfg["run"],
            "start_wind_protocol": {
                "max_time_s": cfg["max_time"],
                "give_up_after_s": cfg["give_up_after"],
                "rel_tol": cfg["rel_tol"],
                "guess_m_s": cfg["start_wind_guess"],
                "definition": "the lowest constant wind at which the crank completes one revolution from rest "
                              "(W-03); the result is the interval (lo, hi]",
            },
            "outcome": "the forward distance of the torso over the driving window (m, higher is better)",
            "start_wind_proxy": {
                "formula": "v* = sqrt(max(0, peak_load_torque) / (gear * 0.5 * rho * Cd * A * r))",
                "source": "the virtual dynamometer of EXPERIMENTS section 32, with the peak load torque rescaled to "
                          "the design's torso mass (the dynamometer weighs the machine with the scenario's "
                          "walker.mass, which is the schema default of 50 kg for a design that declares a torso mass)",
                "cost": "0.56 s per candidate (measured on this machine, the 180-sample torque sweep); cheap enough to "
                        "sit inside the optimisation loop, and about 700 times cheaper than the real start-wind search "
                        "(about 390 s per design)",
            },
        },
        "optimisation": {
            "optimizer": "CmaEs (ask/tell), the same one for every run",
            "seed": args.seed,
            "sigma0": args.sigma0,
            "popsize": args.popsize,
            "max_evals": args.evals,
            "runs": runs,
        },
        "table": table,
        "weighting_sensitivity": weighting_table,
        "proxy_check": proxy_check_summary,
        "worst_gust_sequence": worst_gust_comparison,
        "adversarial_gust_search": adversarial,
        "adversarial_gust_comparison": adversarial_comparison,
        "mujoco_cross_check": cross_check,
        "budget": {
            "candidate_evaluations_per_run": args.evals,
            "popsize": args.popsize,
            "runs": len(runs),
            "scenario_set_size": len(scenarios),
            "physics_evaluations_k2": evaluators["fixed"].evaluations + evaluators["free"].evaluations,
            "start_wind_searches": len(fine_designs),
            "start_wind_attempt_simulations": sum(
                int(m.get("simulations", 0)) for m in measured.values()
            ),
            "wall_time_s": time.time() - t_start,
            "note": "the search is budget-limited; no convergence is claimed and the designs are not shown to be optimal",
        },
        "verdict": verdict,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_clean(report), indent=1, default=float) + "\n")
    try:
        shown = str(out.relative_to(ROOT))
    except ValueError:
        shown = str(out)
    print(f"[w08] wrote {shown} in {time.time() - t_start:.0f}s", flush=True)


def _rank(values: Sequence[float]) -> list[float]:
    """The ranks of a sample (1 = the smallest), ties share the average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        stop = index
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[index]]:
            stop += 1
        average = (index + stop) / 2.0 + 1.0
        for k in range(index, stop + 1):
            ranks[order[k]] = average
        index = stop + 1
    return ranks


def _spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """The Spearman rank correlation of two samples."""
    if len(a) != len(b) or len(a) < 2:
        return float("nan")
    ra, rb = _rank(a), _rank(b)
    mean_a = sum(ra) / len(ra)
    mean_b = sum(rb) / len(rb)
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - mean_a) ** 2 for x in ra) * sum((y - mean_b) ** 2 for y in rb))
    return float(num / den) if den else float("nan")


if __name__ == "__main__":
    main()
