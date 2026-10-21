"""O-07: robust optimisation (CVaR) and adversarial scenario search on the reference Jansen walker.

  python packages/opt/scripts/robust_run.py [--seed 1] [--alpha 0.1] [--scenarios 20] [--evals 32] [--popsize 8]
                                            [--workers 8] [--backend k2] [--timestep 0.001] [--window 2.5]
                                            [--no-cross-check] [--out experiments/robust-optimization.json]

What it does, in order:

1. Declares the scenario space (every axis names its assumption) and samples a scenario set from it with a seeded RNG.
2. Runs the same CMA-ES (ask/tell, from `strandbeest_opt.optimizers`) three times over the same design subspace: against the
   nominal scenario, against the CVaR of the scenario set, and against the worst case of that set.
3. Runs the adversarial scenario search for the reference design and for each of the three optimised designs: the scenario in
   which that particular design does worst.
4. Compares the three designs (plus the reference) at the nominal scenario, over the scenario set (CVaR and worst case) and
   in the adversarial scenario that broke the nominal-optimal design.

The physics is MuJoCo or the independent K2 solver; both are run through `strandbeest_sim.runner`. The forward distance over
a fixed time window is the outcome (higher is better). Everything is seeded, so a rerun with the same arguments gives the same
numbers.

Writes experiments/robust-optimization.json. The search is budget-limited: the number of evaluations is reported, and no
convergence is claimed.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import math
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/common/src"))
sys.path.insert(0, str(ROOT / "packages/sim/src"))
sys.path.insert(0, str(ROOT / "packages/opt/src"))

from strandbeest_common import Design  # noqa: E402
from strandbeest_opt.robust import (  # noqa: E402
    Axis,
    Scenario,
    ScenarioSampler,
    ScenarioSpace,
    adversarial_search,
    compare_designs,
    cvar_lower,
    robust_optimise,
)
from strandbeest_sim.from_design import scenario_from_design  # noqa: E402
from strandbeest_sim.runner import run  # noqa: E402

DESIGN_PATH = ROOT / "schemas/examples/design-jansen-small-6leg.json"
_BASE_DESIGN = json.loads(DESIGN_PATH.read_text())

# The design subspace of this experiment: three named linkage parameters of the Jansen topology, the other ten frozen at the
# reference values. CMA-ES over the full 13 parameters with a few dozen physics evaluations would move nothing, so the
# subspace is declared here and reported in the JSON.
SEARCH_PARAMS = ("m", "a", "h")  # crank length, hip offset, thigh
SEARCH_BOUNDS = {"m": (12.0, 18.0), "a": (36.0, 40.0), "h": (60.0, 70.0)}
SEARCH_ASSUMPTIONS = {
    "m": "assumption: the crank length of the reference design is 15 units; the search range is a declared box around it, "
         "not an optimum found anywhere",
    "a": "assumption: the hip offset of the reference design is 38 units; the search range is a declared box around it",
    "h": "assumption: the thigh length of the reference design is 65.7 units; the search range is a declared box around it",
}

# The number of crank angles at which the linkage must assemble (the same count as strandbeest_opt.fitness.PROBES).
ASSEMBLY_PROBES = 24
# The outcome of a design that cannot be assembled (or whose solver run fails): it does not walk at all. The value is far
# below any real distance, so the optimiser avoids it.
INFEASIBLE_DISTANCE_M = -1.0
# A walker that moves less than this in the driving window counts as "not walking". Assumption: the reference design covers
# 0.59 m at the nominal scenario in the same window, so 1 cm is about 2 % of it.
WALK_THRESHOLD_M = 0.01


def _params_for(genome) -> dict[str, float]:
    params = {k: float(v) for k, v in _BASE_DESIGN["linkage"]["params"].items()}
    for name, value in zip(SEARCH_PARAMS, genome):
        params[name] = float(value)
    return params


def _space() -> ScenarioSpace:
    """The declared scenario space. Every number is a named assumption (AGENTS.md)."""
    return ScenarioSpace(
        name="o07-wind-terrain-friction-v1",
        axes=(
            Axis(name="wind_speed_m_s", kind="continuous", low=0.1, high=14.0, unit="m/s",
                 assumption="assumption: the reference walker's critical start wind is ~0.69 m/s (W-06, one model, E0); the "
                            "range spans 'below the start threshold' to '2.8x the nominal breeze'. Not a measurement."),
            Axis(name="wind_kind", kind="categorical", values=("constant", "gusts", "profile_turbulent"),
                 assumption="assumption: the three wind models registered in strandbeest_sim.winds (W-04). Which of them "
                            "occurs on a given day is not known."),
            Axis(name="gust_amplitude_m_s", kind="continuous", low=0.5, high=6.0, unit="m/s",
                 assumption="assumption: the gust peak deviation; the winds registry default is 1.0 m/s (not measured)."),
            Axis(name="gust_period_s", kind="continuous", low=2.0, high=15.0, unit="s",
                 assumption="assumption: the winds registry default is 6 s (not measured)."),
            Axis(name="turbulence_intensity", kind="continuous", low=0.05, high=0.30, unit="-",
                 assumption="assumption: the Dryden turbulence intensity I_u; the winds registry default is 0.15 (W-04)."),
            Axis(name="turbulence_seed", kind="integer", low=1, high=8,
                 assumption="assumption: which turbulence realisation is drawn; only the index is defined."),
            Axis(name="yaw_deg", kind="continuous", low=0.0, high=60.0, unit="deg",
                 assumption="assumption: the wind direction stays within 60 deg of the walking direction. A head wind is "
                            "excluded on purpose: the wind model gives it no drive component at all, so it would be a trivial "
                            "failure for every design and would hide the differences between them."),
            Axis(name="terrain_kind", kind="categorical", values=("flat", "slope", "bumps"),
                 assumption="assumption: the three terrain plans of strandbeest_sim.terrains that a walking beach can have."),
            Axis(name="slope_deg", kind="continuous", low=0.0, high=8.0, unit="deg",
                 assumption="assumption: an uphill slope of up to 8 deg; the terrain registry models it by tilting gravity."),
            Axis(name="friction", kind="continuous", low=0.3, high=2.5, unit="-",
                 assumption="assumption: the ground friction coefficient; V-04 used 0.5 / 1.5 / 2.5."),
            Axis(name="bump_count", kind="integer", low=4, high=16,
                 assumption="assumption: the number of random bumps of the 'bumps' terrain."),
            Axis(name="bump_max_height_m", kind="continuous", low=0.005, high=0.030, unit="m",
                 assumption="assumption: the bump height; the terrain registry default is 0.015 m."),
            Axis(name="bump_seed", kind="integer", low=1, high=8,
                 assumption="assumption: the placement seed of the bumps."),
        ),
        nominal=Scenario(
            wind_speed_m_s=5.0,
            wind_kind="constant",
            wind_params={"yaw_deg": 0.0},
            terrain_kind="flat",
            friction=1.5,
            slope_deg=0.0,
            label="nominal: constant 5.0 m/s, flat ground, mu=1.5, yaw 0 deg",
        ),
        notes="the declared scenario space of O-07; the sampled set is written to the output file so that every number below "
              "can be traced back to the scenarios that produced it",
    )


# ---------------------------------------------------------------------------------------------------------------------
# The physics
# ---------------------------------------------------------------------------------------------------------------------


def _simulate(task) -> tuple[float, float]:
    """Run one scenario for one design. Returns (forward distance in m, crank revolutions)."""
    params, scenario, cfg = task
    try:
        return _simulate_inner(params, scenario, cfg)
    except Exception:  # a worker crash is invisible otherwise (the pool only re-raises the message)
        import traceback

        traceback.print_exc()
        raise


def _simulate_inner(params, scenario, cfg) -> tuple[float, float]:
    from strandbeest_common.linkage import load_spec, solve_pose
    from strandbeest_sim.backends.k2_backend import K2Backend

    doc = copy.deepcopy(_BASE_DESIGN)
    doc["linkage"]["params"] = params
    # A genome that cannot assemble at some crank angle does not walk at all: the kinematics are checked first (the same 24
    # probes as strandbeest_opt.fitness), which also saves the physics run.
    spec = load_spec(doc["linkage"])
    if any(solve_pose(spec, 2 * math.pi * i / ASSEMBLY_PROBES) is None for i in range(ASSEMBLY_PROBES)):
        return (INFEASIBLE_DISTANCE_M, 0.0)
    overrides = scenario.overrides()
    overrides["drive"] = {"kind": cfg["drive_kind"]}
    overrides["run"] = dict(cfg["run"])
    sc = scenario_from_design(Design(doc), overrides)
    backend = K2Backend(timestep=cfg["timestep"]) if cfg["backend"] == "k2" else cfg["backend"]
    try:
        res = run(sc, backend=backend)
    except Exception as exc:  # a solver blow-up is a design that does not walk, not a crash of the experiment
        print(f"[o07] simulation failed ({type(exc).__name__}: {exc}); the design counts as not walking", flush=True)
        return (INFEASIBLE_DISTANCE_M, 0.0)
    distance = float(res.x[-1] - res.x[0]) if len(res.x) else 0.0
    revs = float(res.psi[-1]) / (2 * math.pi) if len(res.psi) else 0.0
    return distance, revs


class SimEvaluator:
    """The injected physics: forward distance (higher is better) of a design in a scenario.

    Implements the optional batch protocol of `strandbeest_opt.robust`: the scenarios of one candidate are run side by side,
    because a simulator run is the expensive part of this experiment.
    """

    def __init__(self, pool: "mp.pool.Pool | None", cfg: dict) -> None:
        self._pool = pool
        self._cfg = cfg
        self.evaluations = 0

    def __call__(self, genome, scenario: Scenario) -> float:
        return self.evaluate_batch(genome, [scenario])[0]

    def evaluate_batch(self, genome, scenarios) -> list[float]:
        params = _params_for(genome)
        tasks = [(params, sc, self._cfg) for sc in scenarios]
        if self._pool is None:
            results = [_simulate(t) for t in tasks]
        else:
            results = list(self._pool.map(_simulate, tasks))
        self.evaluations += len(tasks)
        return [r[0] for r in results]


class OnlyWalking:
    """The evaluator of the "hardest survivable scenario" search: +inf for a scenario in which the design does not walk.

    It offers the batch protocol, so the scenarios of one candidate run side by side (the plain closure would have been
    evaluated one by one, which is eight times slower for the same number of physics runs).
    """

    def __init__(self, evaluator: SimEvaluator) -> None:
        self._evaluator = evaluator

    def __call__(self, genome, scenario: Scenario) -> float:
        distance = self._evaluator(genome, scenario)
        return distance if distance > WALK_THRESHOLD_M else math.inf

    def evaluate_batch(self, genome, scenarios) -> list[float]:
        distances = self._evaluator.evaluate_batch(genome, scenarios)
        return [d if d > WALK_THRESHOLD_M else math.inf for d in distances]


# ---------------------------------------------------------------------------------------------------------------------
# The experiment
# ---------------------------------------------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--alpha", type=float, default=0.1, help="tail probability of the CVaR (WIND.md: 0.1 = worst 10 %)")
    ap.add_argument("--scenarios", type=int, default=20, help="size of the sampled scenario set")
    ap.add_argument("--evals", type=int, default=32, help="candidate evaluations per CMA-ES run")
    ap.add_argument("--popsize", type=int, default=8)
    ap.add_argument("--workers", type=int, default=8, help="parallel simulator processes")
    ap.add_argument("--backend", default="k2", choices=("k2", "mujoco"))
    ap.add_argument("--timestep", type=float, default=1e-3, help="solver time step (s)")
    ap.add_argument("--window", type=float, default=2.5, help="driving window (s); the outcome is the distance in that window")
    ap.add_argument("--settle", type=float, default=0.2)
    ap.add_argument("--random-pool", type=int, default=16, help="scenarios drawn for the adversarial search")
    ap.add_argument("--refine-budget", type=int, default=112, help="scenario evaluations of the adversarial refinement")
    ap.add_argument("--no-cross-check", action="store_true", help="skip the MuJoCo cross-check of the final table")
    ap.add_argument("--out", default=str(ROOT / "experiments/robust-optimization.json"))
    args = ap.parse_args()

    cfg = {
        "backend": args.backend,
        "timestep": args.timestep,
        "drive_kind": "sail",
        "run": {
            "revolutions": 10.0,
            "settle": args.settle,
            "max_time": args.window,
            "frame_rate": 0,
            "give_up_after": args.window * 0.6,
        },
    }
    space = _space()
    x0 = [float(_BASE_DESIGN["linkage"]["params"][n]) for n in SEARCH_PARAMS]
    lower = [SEARCH_BOUNDS[n][0] for n in SEARCH_PARAMS]
    upper = [SEARCH_BOUNDS[n][1] for n in SEARCH_PARAMS]

    t_start = time.time()
    workers = max(1, min(args.workers, os.cpu_count() or 1))
    print(f"[o07] backend={args.backend} timestep={args.timestep} window={args.window}s workers={workers}", flush=True)

    with mp.Pool(processes=workers) as pool:
        evaluator = SimEvaluator(pool, cfg)

        # 1. the sampled scenario set ---------------------------------------------------------------------------------
        sampler = ScenarioSampler(space, seed=args.seed)
        scenarios = sampler.sample(args.scenarios)
        print(f"[o07] sampled {len(scenarios)} scenarios (seed {args.seed})", flush=True)

        # 2. the three CMA-ES runs ------------------------------------------------------------------------------------
        runs = robust_optimise(
            space=space,
            scenarios=scenarios,
            evaluate=evaluator,
            x0=x0,
            sigma0=1.0,
            bounds=(lower, upper),
            alpha=args.alpha,
            seed=args.seed,
            max_evals=args.evals,
            popsize=args.popsize,
        )
        for name, run_result in runs.items():
            print(
                f"[o07] {name:11s} value {run_result.value:+.4f} m "
                f"candidates {run_result.candidate_evaluations} scenarios {run_result.scenario_evaluations} "
                f"wall {run_result.wall_time_s:.1f}s",
                flush=True,
            )

        # 3. the adversarial search for every design -------------------------------------------------------------------
        designs = {
            "reference": x0,
            "nominal_optimum": runs["nominal"].genome,
            "cvar_optimum": runs["cvar"].genome,
            "worst_case_optimum": runs["worst_case"].genome,
        }
        adversarial = {}
        for name, genome in designs.items():
            t0 = time.time()
            result = adversarial_search(
                space,
                genome,
                evaluator,
                seed=args.seed,
                n_random=args.random_pool,
                n_refine=args.refine_budget,
            )
            adversarial[name] = result
            print(
                f"[o07] adversarial[{name}]: worst {result.value:+.4f} m in '{result.scenario.describe()}' "
                f"(pool {result.random_value:+.4f} m, {result.evaluations} evaluations, {time.time() - t0:.1f}s)",
                flush=True,
            )

        # 3b. the hardest scenario a design still walks in (a scenario in which it fails is useless for the comparison) -----
        adversarial_surviving = {}
        only_walking = OnlyWalking(evaluator)
        for name in ("nominal_optimum", "cvar_optimum", "worst_case_optimum"):
            genome = designs[name]
            t0 = time.time()
            result = adversarial_search(
                space,
                genome,
                only_walking,
                seed=args.seed,
                n_random=args.random_pool,
                n_refine=args.refine_budget,
            )
            adversarial_surviving[name] = result
            print(
                f"[o07] hardest survivable[{name}]: {result.value:+.4f} m in '{result.scenario.describe()}' "
                f"({result.evaluations} evaluations, {time.time() - t0:.1f}s)",
                flush=True,
            )

        # 4. the three-way comparison ------------------------------------------------------------------------------------
        worst_for_nominal = adversarial["nominal_optimum"].scenario
        hardest_for_nominal = adversarial_surviving["nominal_optimum"].scenario
        rows = compare_designs(
            designs,
            space=space,
            scenarios=scenarios,
            evaluate=evaluator,
            alpha=args.alpha,
            extra={
                "adversarial_failure_of_nominal_optimum": worst_for_nominal,
                "hardest_survivable_of_nominal_optimum": hardest_for_nominal,
            },
            failure_threshold=WALK_THRESHOLD_M,
        )
        for row in rows:
            print(
                f"[o07] {row.name:20s} nominal {row.nominal:+.4f} m  cvar {row.cvar:+.4f} m  "
                f"worst {row.worst_case:+.4f} m  mean {row.mean:+.4f} m  failures {row.failures}/{len(scenarios)}  "
                f"failure {row.extra_values.get('adversarial_failure_of_nominal_optimum', float('nan')):+.4f} m  "
                f"survivable {row.extra_values.get('hardest_survivable_of_nominal_optimum', float('nan')):+.4f} m",
                flush=True,
            )

        # 5. the same table with a larger tail, so the reader sees how much the estimator depends on alpha ------------------
        alpha_alt = 0.3
        cvar_alt = {row.name: cvar_lower(list(row.scenario_values.values()), alpha_alt) for row in rows}

        # 6. sensitivity: the same designs on a different ground friction -----------------------------------------------
        # Only the friction changes: the scenario set and the adversarial scenario keep every other parameter, so the
        # difference between the tables is the friction alone.
        friction_check = []
        for mu in (0.5, 2.5):
            mu_space = dataclasses.replace(space, nominal=space.nominal.with_friction(mu))
            mu_scenarios = [sc.with_friction(mu) for sc in scenarios]
            mu_rows = compare_designs(
                designs,
                space=mu_space,
                scenarios=mu_scenarios,
                evaluate=evaluator,
                alpha=args.alpha,
                extra={
                    "adversarial_failure_of_nominal_optimum": worst_for_nominal.with_friction(mu),
                    "hardest_survivable_of_nominal_optimum": hardest_for_nominal.with_friction(mu),
                },
                failure_threshold=WALK_THRESHOLD_M,
            )
            entry = {
                "friction": mu,
                "table": [r.to_dict() for r in mu_rows],
                "headline_in_set": _headline_in_set(mu_rows),
                "headline_at_adversarial_failure": _headline_at_key(mu_rows, "adversarial_failure_of_nominal_optimum"),
                "headline_at_hardest_survivable": _headline_at_key(mu_rows, "hardest_survivable_of_nominal_optimum"),
            }
            friction_check.append(entry)
            print(
                f"[o07] friction mu={mu}: in-set worst scenario "
                f"nominal {entry['headline_in_set']['nominal_optimum_m']:+.4f} m, "
                f"cvar {entry['headline_in_set']['cvar_optimum_m']:+.4f} m, "
                f"cvar beats nominal: {entry['headline_in_set']['cvar_beats_nominal']}",
                flush=True,
            )

        # 7. sensitivity: a different CMA-ES seed (the same scenario set) ----------------------------------------------
        seed_runs = robust_optimise(
            space=space,
            scenarios=scenarios,
            evaluate=evaluator,
            x0=x0,
            sigma0=1.0,
            bounds=(lower, upper),
            alpha=args.alpha,
            seed=args.seed + 1,
            max_evals=args.evals,
            popsize=args.popsize,
        )
        seed_designs = {
            "nominal_optimum": seed_runs["nominal"].genome,
            "cvar_optimum": seed_runs["cvar"].genome,
            "worst_case_optimum": seed_runs["worst_case"].genome,
        }
        seed_rows = compare_designs(
            seed_designs,
            space=space,
            scenarios=scenarios,
            evaluate=evaluator,
            alpha=args.alpha,
            extra={
                "adversarial_failure_of_nominal_optimum": worst_for_nominal,
                "hardest_survivable_of_nominal_optimum": hardest_for_nominal,
            },
            failure_threshold=WALK_THRESHOLD_M,
        )
        seed_check = {
            "seed": args.seed + 1,
            "optimisation": {name: r.to_dict() for name, r in seed_runs.items()},
            "table": [r.to_dict() for r in seed_rows],
            "headline_in_set": _headline_in_set(seed_rows),
            "headline_at_adversarial_failure": _headline_at_key(seed_rows, "adversarial_failure_of_nominal_optimum"),
            "headline_at_hardest_survivable": _headline_at_key(seed_rows, "hardest_survivable_of_nominal_optimum"),
        }
        print(
            f"[o07] cma-es seed {args.seed + 1}: at the adversarial failure scenario "
            f"nominal {seed_check['headline_at_adversarial_failure']['nominal_optimum_m']:+.4f} m, "
            f"cvar {seed_check['headline_at_adversarial_failure']['cvar_optimum_m']:+.4f} m, "
            f"cvar beats nominal: {seed_check['headline_at_adversarial_failure']['cvar_beats_nominal']}",
            flush=True,
        )

        # 8. sensitivity: a different scenario-set seed (the same designs) ----------------------------------------------
        alt_scenarios = ScenarioSampler(space, seed=args.seed + 1).sample(args.scenarios)
        alt_rows = compare_designs(
            designs,
            space=space,
            scenarios=alt_scenarios,
            evaluate=evaluator,
            alpha=args.alpha,
            extra={
                "adversarial_failure_of_nominal_optimum": worst_for_nominal,
                "hardest_survivable_of_nominal_optimum": hardest_for_nominal,
            },
            failure_threshold=WALK_THRESHOLD_M,
        )
        scenario_seed_check = {
            "seed": args.seed + 1,
            "scenarios": [s.to_dict() for s in alt_scenarios],
            "table": [r.to_dict() for r in alt_rows],
            "headline_in_set": _headline_in_set(alt_rows),
            "headline_at_adversarial_failure": _headline_at_key(alt_rows, "adversarial_failure_of_nominal_optimum"),
            "headline_at_hardest_survivable": _headline_at_key(alt_rows, "hardest_survivable_of_nominal_optimum"),
        }
        print(
            f"[o07] scenario seed {args.seed + 1}: in-set worst scenario "
            f"nominal {scenario_seed_check['headline_in_set']['nominal_optimum_m']:+.4f} m, "
            f"cvar {scenario_seed_check['headline_in_set']['cvar_optimum_m']:+.4f} m, "
            f"cvar beats nominal: {scenario_seed_check['headline_in_set']['cvar_beats_nominal']}",
            flush=True,
        )

        # 9. the solver time-step check (a check, not a validation) ----------------------------------------------------------
        timestep_check = []
        for ts in (5e-4, 1e-3, 2e-3):
            check_cfg = dict(cfg)
            check_cfg["timestep"] = ts
            check_eval = SimEvaluator(pool, check_cfg)
            distance = check_eval(x0, space.nominal)
            timestep_check.append({"timestep": ts, "nominal_distance_m": distance})

        # 10. the MuJoCo cross-check of the final table ---------------------------------------------------------------------
        cross_check = None
        cross_check_headline = None
        if not args.no_cross_check and args.backend == "k2":
            mujoco_cfg = dict(cfg)
            mujoco_cfg["backend"] = "mujoco"
            mujoco_eval = SimEvaluator(pool, mujoco_cfg)
            cross_check = {
                name: {
                    "nominal_m": mujoco_eval(genome, space.nominal),
                    "adversarial_failure_of_nominal_optimum_m": mujoco_eval(genome, worst_for_nominal),
                    "hardest_survivable_of_nominal_optimum_m": mujoco_eval(genome, hardest_for_nominal),
                }
                for name, genome in designs.items()
            }
            # the same headline under the second solver: does the robust design still win?
            cross_check_headline = {
                key: {
                    "nominal_optimum_m": cross_check["nominal_optimum"][key],
                    "cvar_optimum_m": cross_check["cvar_optimum"][key],
                    "worst_case_optimum_m": cross_check["worst_case_optimum"][key],
                    "cvar_minus_nominal_m": cross_check["cvar_optimum"][key] - cross_check["nominal_optimum"][key],
                    "worst_case_minus_nominal_m": (
                        cross_check["worst_case_optimum"][key] - cross_check["nominal_optimum"][key]
                    ),
                    "cvar_beats_nominal": _gt(
                        cross_check["cvar_optimum"][key], cross_check["nominal_optimum"][key]
                    ),
                    "worst_case_beats_nominal": _gt(
                        cross_check["worst_case_optimum"][key], cross_check["nominal_optimum"][key]
                    ),
                }
                for key in (
                    "nominal_m",
                    "adversarial_failure_of_nominal_optimum_m",
                    "hardest_survivable_of_nominal_optimum_m",
                )
            }
            # 10b. the adversarial search itself under the second solver (a smaller budget: MuJoCo is much slower) ----
            # The question of criterion 1 is "which scenario breaks this design", so the search has to be repeated with the
            # other solver, not only the final table.
            mujoco_adversarial = {}
            for name in ("reference", "nominal_optimum", "cvar_optimum"):
                t0 = time.time()
                res = adversarial_search(
                    space,
                    designs[name],
                    mujoco_eval,
                    seed=args.seed,
                    n_random=max(4, args.random_pool // 2),
                    n_refine=max(8, args.refine_budget // 4),
                )
                mujoco_adversarial[name] = res.to_dict()
                print(
                    f"[o07] mujoco adversarial[{name}]: worst {res.value:+.4f} m in '{res.scenario.describe()}' "
                    f"(pool {res.random_value:+.4f} m, {res.evaluations} evaluations, {time.time() - t0:.1f}s)",
                    flush=True,
                )
            cross_check_headline["adversarial_search_under_mujoco"] = mujoco_adversarial
            print(f"[o07] mujoco cross-check done ({time.time() - t_start:.0f}s)", flush=True)

    # 11. the verdict ---------------------------------------------------------------------------------------------------
    by_name = {row.name: row for row in rows}
    nominal_row = by_name["nominal_optimum"]
    cvar_row = by_name["cvar_optimum"]
    worst_row = by_name["worst_case_optimum"]
    key_fail = "adversarial_failure_of_nominal_optimum"
    key_hard = "hardest_survivable_of_nominal_optimum"

    def _level(key: str, scenario: Scenario) -> dict:
        return {
            "scenario": scenario.to_dict(),
            "nominal_optimum_m": nominal_row.extra_values.get(key),
            "cvar_optimum_m": cvar_row.extra_values.get(key),
            "worst_case_optimum_m": worst_row.extra_values.get(key),
            "cvar_beats_nominal": _gt(cvar_row.extra_values.get(key), nominal_row.extra_values.get(key)),
            "worst_case_beats_nominal": _gt(worst_row.extra_values.get(key), nominal_row.extra_values.get(key)),
        }

    level_a = _level(key_fail, worst_for_nominal)
    level_b = _level(key_hard, hardest_for_nominal)
    verdict = {
        "criterion": "the robust design beats the nominal-optimal design in the worst scenario",
        "level_a_failure_scenario": level_a,
        "level_b_hardest_survivable_scenario": level_b,
        "note": "level A is the strict reading (the worst scenario of the whole space, where the nominal-optimal design "
                "fails); level B is the hardest scenario the nominal-optimal design still walks in, which is where the "
                "designs can be told apart. Both are reported, whatever they say.",
    }
    shown = []
    if level_a["cvar_beats_nominal"] or level_a["worst_case_beats_nominal"]:
        shown.append("level A")
    if level_b["cvar_beats_nominal"] or level_b["worst_case_beats_nominal"]:
        shown.append("level B")
    verdict["verdict"] = (
        f"demonstrated in {', '.join(shown)}" if shown else "NOT demonstrated in either reading"
    )
    # the same question under the perturbations of section 7: does the robust design still win when the friction, the
    # optimiser seed, the scenario set or the solver changes?
    verdict["sensitivity_cvar_beats_nominal_at_adversarial_failure"] = {
        **{f"friction_{e['friction']}": e["headline_at_adversarial_failure"]["cvar_beats_nominal"] for e in friction_check},
        "cma_es_seed": seed_check["headline_at_adversarial_failure"]["cvar_beats_nominal"],
        "scenario_set_seed": scenario_seed_check["headline_at_adversarial_failure"]["cvar_beats_nominal"],
        "mujoco": (cross_check_headline or {}).get("adversarial_failure_of_nominal_optimum_m", {}).get("cvar_beats_nominal"),
    }

    report = {
        "card": "O-07",
        "generated_by": "packages/opt/scripts/robust_run.py",
        "seed": args.seed,
        "alpha": args.alpha,
        "scenario_space": space.to_dict(),
        "sampled_scenarios": [s.to_dict() for s in scenarios],
        "design_space": {
            "topology": "Jansen (contracts/kinematics/jansen.json topology of the reference design)",
            "searched_params": list(SEARCH_PARAMS),
            "frozen_params": sorted(set(_BASE_DESIGN["linkage"]["params"]) - set(SEARCH_PARAMS)),
            "bounds": {n: list(SEARCH_BOUNDS[n]) for n in SEARCH_PARAMS},
            "assumptions": SEARCH_ASSUMPTIONS,
            "x0": x0,
            "sigma0": 1.0,
            "note": "a declared 3-parameter subspace around the reference design: with a few dozen physics evaluations a "
                    "CMA-ES over all 13 linkage lengths would move nothing, so the subspace is stated instead of being hidden",
        },
        "physics": {
            "backend": args.backend,
            "timestep_s": args.timestep,
            "drive": "sail (wind driven)",
            "run": cfg["run"],
            "outcome": "forward distance of the torso over the driving window (m, higher is better)",
            "timestep_check": timestep_check,
            "mujoco_cross_check": cross_check,
        },
        "optimisation": {name: r.to_dict() for name, r in runs.items()},
        "adversarial": {name: r.to_dict() for name, r in adversarial.items()},
        "adversarial_hardest_survivable": {name: r.to_dict() for name, r in adversarial_surviving.items()},
        "comparison": [row.to_dict() for row in rows],
        "comparison_cvar_alpha_0p3": cvar_alt,
        "sensitivity": {
            "friction": friction_check,
            "cma_es_seed": seed_check,
            "scenario_set_seed": scenario_seed_check,
            "mujoco_headline": cross_check_headline,
        },
        "budget": {
            "candidate_evaluations_per_run": args.evals,
            "popsize": args.popsize,
            "scenario_set_size": len(scenarios),
            "physics_evaluations_total": evaluator.evaluations,
            "wall_time_s": time.time() - t_start,
            "note": "the search is budget-limited; no convergence is claimed and the designs are not shown to be optimal",
        },
        "verdict": verdict,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_clean(report), indent=1, default=float) + "\n")
    try:
        shown_path = str(out.relative_to(ROOT))
    except ValueError:
        shown_path = str(out)
    print(f"[o07] wrote {shown_path} in {time.time() - t_start:.0f}s", flush=True)
    print(f"[o07] verdict: {verdict['verdict']}", flush=True)


def _gt(a, b) -> bool | None:
    if a is None or b is None:
        return None
    return bool(a > b)


def _diff(a, b) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def _headline(values: dict, scenario: str) -> dict:
    """The one comparison the card asks for, at one named scenario: does the robust design beat the nominal one?

    `values` maps the three design names to their outcome in that scenario.
    """
    nom = values.get("nominal_optimum")
    cvar = values.get("cvar_optimum")
    worst = values.get("worst_case_optimum")
    return {
        "scenario": scenario,
        "nominal_optimum_m": nom,
        "cvar_optimum_m": cvar,
        "worst_case_optimum_m": worst,
        "cvar_minus_nominal_m": _diff(cvar, nom),
        "worst_case_minus_nominal_m": _diff(worst, nom),
        "cvar_beats_nominal": _gt(cvar, nom),
        "worst_case_beats_nominal": _gt(worst, nom),
    }


def _headline_at_key(rows, key: str) -> dict:
    """The headline at a named extra scenario of the comparison table."""
    by = {r.name: r for r in rows}
    names = ("nominal_optimum", "cvar_optimum", "worst_case_optimum")
    return _headline({n: by[n].extra_values.get(key) for n in names}, key)


def _headline_in_set(rows) -> dict:
    """The headline at the scenario of the set in which the nominal-optimal design does worst.

    The scenario values of every design are keyed by the same scenario description, so the comparison costs no extra physics.
    """
    by = {r.name: r for r in rows}
    nom = by["nominal_optimum"]
    key = min(nom.scenario_values, key=nom.scenario_values.get)
    names = ("nominal_optimum", "cvar_optimum", "worst_case_optimum")
    return _headline({n: by[n].scenario_values.get(key) for n in names}, key)


def _clean(obj):
    """Replace the non-finite floats (inf = the design does not walk anywhere) by null, so the file is strict JSON."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


if __name__ == "__main__":
    main()
