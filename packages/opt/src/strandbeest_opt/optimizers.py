"""Mature optimisers behind one ask/tell interface (O-01).

    opt = CmaEs(x0, sigma0, bounds, seed=1)          # or Nsga2(...)
    while not opt.stop():
        xs = opt.ask()
        opt.tell(xs, [fitness(x) for x in xs])        # fitness: higher is better
    opt.best, opt.best_f

The evaluation loop belongs to the caller, so the same optimiser can drive the kinematic fitness, the MuJoCo simulator, a
multi-fidelity filter or an agent's budget. CMA-ES is Hansen's reference implementation (`cma`); NSGA-II is pymoo's."""

from __future__ import annotations

from typing import Callable, Protocol, Sequence

import numpy as np


class Optimizer(Protocol):
    best: list[float]
    best_f: float

    def ask(self) -> list[list[float]]: ...
    def tell(self, xs: Sequence[Sequence[float]], fs: Sequence[float]) -> None: ...
    def stop(self) -> bool: ...


class CmaEs:
    """CMA-ES for one objective (maximised), box-bounded."""

    def __init__(self, x0: Sequence[float], sigma0: float, bounds: tuple[Sequence[float], Sequence[float]] | None = None,
                 seed: int = 1, popsize: int | None = None, max_evals: int | None = None) -> None:
        import cma

        opts: dict = {"seed": seed, "verbose": -9}
        if bounds is not None:
            opts["bounds"] = [list(map(float, bounds[0])), list(map(float, bounds[1]))]
        if popsize:
            opts["popsize"] = popsize
        if max_evals:
            opts["maxfevals"] = max_evals
        self._es = cma.CMAEvolutionStrategy(list(map(float, x0)), sigma0, opts)
        self.best: list[float] = list(map(float, x0))
        self.best_f = float("-inf")
        self.evals = 0

    def ask(self) -> list[list[float]]:
        return [list(map(float, x)) for x in self._es.ask()]

    def tell(self, xs, fs) -> None:
        for x, f in zip(xs, fs):
            if f > self.best_f:
                self.best, self.best_f = list(map(float, x)), float(f)
        self.evals += len(xs)
        self._es.tell([list(x) for x in xs], [-float(f) for f in fs])  # cma minimises

    def stop(self) -> bool:
        return bool(self._es.stop())


class Nsga2:
    """NSGA-II for several objectives (all maximised). `pareto()` returns the current non-dominated set."""

    def __init__(self, n_var: int, n_obj: int, bounds: tuple[Sequence[float], Sequence[float]], seed: int = 1, pop_size: int = 40) -> None:
        from pymoo.algorithms.moo.nsga2 import NSGA2
        from pymoo.core.problem import Problem
        from pymoo.termination import get_termination

        class _P(Problem):
            def __init__(self):
                super().__init__(n_var=n_var, n_obj=n_obj, xl=np.array(bounds[0], float), xu=np.array(bounds[1], float))

        self._problem = _P()
        self._algo = NSGA2(pop_size=pop_size, eliminate_duplicates=True)
        self._algo.setup(self._problem, get_termination("n_gen", 10**9), seed=seed)
        self._pop = None
        self.best: list[float] = []
        self.best_f = float("-inf")
        self.n_obj = n_obj

    def ask(self) -> list[list[float]]:
        self._pop = self._algo.ask()
        return [list(map(float, x)) for x in self._pop.get("X")]

    def tell(self, xs, fs) -> None:
        from pymoo.core.evaluator import Evaluator  # noqa: F401

        F = -np.asarray(fs, float).reshape(len(xs), self.n_obj)  # pymoo minimises
        self._pop.set("F", F)
        self._algo.evaluator.n_eval += len(xs)
        self._algo.tell(infills=self._pop)
        s = F.sum(axis=1)
        k = int(np.argmin(s))
        if -s[k] > self.best_f:
            self.best, self.best_f = list(map(float, xs[k])), float(-s[k])

    def stop(self) -> bool:
        return False

    def pareto(self) -> tuple[np.ndarray, np.ndarray]:
        """(X, F) of the non-dominated solutions so far, F in the maximised sense."""
        opt = self._algo.opt
        return opt.get("X"), -opt.get("F")


def optimize(opt: Optimizer, fitness: Callable[[list[float]], float], max_evals: int) -> tuple[list[float], float, list[float]]:
    """Drive an optimiser with a scalar fitness until it stops or `max_evals` is spent; returns (best, best_f, best-so-far per generation)."""
    history: list[float] = []
    evals = 0
    while not opt.stop() and evals < max_evals:
        xs = opt.ask()
        opt.tell(xs, [fitness(x) for x in xs])
        evals += len(xs)
        history.append(opt.best_f)
    return opt.best, opt.best_f, history
