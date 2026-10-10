"""O-01: CMA-ES and NSGA-II behind ask/tell."""
import numpy as np
import pytest
from strandbeest_opt import CmaEs, Nsga2, optimize


def sphere(x):
    return -float(np.sum((np.asarray(x) - 3.0) ** 2))


def test_cmaes_finds_the_optimum_of_a_smooth_function_and_respects_the_bounds():
    opt = CmaEs([0.0] * 5, 2.0, ([-10.0] * 5, [10.0] * 5), seed=3)
    seen = []

    def f(x):
        seen.append(x)
        return sphere(x)

    best, best_f, hist = optimize(opt, f, 4000)
    assert best_f > -1e-6 and np.allclose(best, 3.0, atol=1e-3)
    assert all(-10.0 <= v <= 10.0 for x in seen for v in x)
    assert hist == sorted(hist)  # best-so-far never gets worse


def test_cmaes_is_reproducible_for_a_seed():
    def run(seed):
        return optimize(CmaEs([0.0] * 3, 1.0, seed=seed), sphere, 600)[:2]

    assert run(5) == run(5) and run(5) != run(6)


def test_cmaes_handles_a_cliff_of_penalties_like_the_gait_fitness_has():
    # infeasible half-space with graded penalties, optimum just inside the feasible half
    def f(x):
        return -10 + 5 * (1 + np.tanh(x[0])) / 2 if x[0] < 0 else 1.0 - (x[0] - 1.0) ** 2 - x[1] ** 2

    best, best_f, _ = optimize(CmaEs([-2.0, 2.0], 1.0, ([-5, -5], [5, 5]), seed=1), f, 3000)
    assert best_f > 0.99 and best[0] > 0


def test_nsga2_traces_a_pareto_front_through_ask_tell():
    # maximise f1 = x0 and f2 = 1 - x0 (a trade-off), x1 only hurts both
    opt = Nsga2(2, 2, ([0.0, 0.0], [1.0, 1.0]), seed=2, pop_size=24)
    for _ in range(30):
        xs = opt.ask()
        opt.tell(xs, [[x[0] - x[1], 1 - x[0] - x[1]] for x in xs])
    X, F = opt.pareto()
    assert len(X) >= 10
    assert np.all(X[:, 1] < 0.05)  # the useless variable is driven to zero
    assert F[:, 0].max() > 0.9 and F[:, 1].max() > 0.9  # both ends of the front are found
    assert np.allclose(F[:, 0] + F[:, 1], 1 - 2 * X[:, 1], atol=1e-9)
