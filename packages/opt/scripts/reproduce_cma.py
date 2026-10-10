"""O-01: the objective-driven blind search of experiments/reproduce-jansen (section 1B of docs/EXPERIMENTS.md) with CMA-ES.

Same objective (flat-stroke fitness), same search box (uniform [5, 80] per length, Jansen's topology), same seeds 1..20. The
old result is the custom GA of packages/core (population 150 x 500 generations = 75k evaluations). CMA-ES gets
`--evals` evaluations per seed (default 12000) so the table compares two optimisers on one objective at unequal budgets,
which is stated in the table.

  python packages/opt/scripts/reproduce_cma.py [--seeds 20] [--evals 12000]  -> experiments/reproduce-jansen-cmaes.json
"""
import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/common/src"))
from strandbeest_common.gait import foot_path  # noqa: E402
from strandbeest_opt import CmaEs, GenomeSpace, fitness_flat_stroke, optimize, path_distance  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", type=int, default=20)
ap.add_argument("--evals", type=int, default=12000)
ap.add_argument("--popsize", type=int, default=40)
a = ap.parse_args()

jansen = json.loads((ROOT / "contracts/kinematics/jansen.json").read_text())["spec"]
space = GenomeSpace.of(jansen)
fit = fitness_flat_stroke(space)
jansen_g = space.to_genome()
jansen_fit = fit(jansen_g)
jansen_foot = foot_path(space.to_spec(jansen_g), 180)
rows = []
for seed in range(1, a.seeds + 1):
    rng_start = [40.0] * len(space.names)
    opt = CmaEs(rng_start, 0.3 * 75, ([5.0] * len(space.names), [80.0] * len(space.names)), seed=seed, popsize=a.popsize)
    best, best_f, hist = optimize(opt, fit, a.evals)
    foot = foot_path(space.to_spec(best), 180)
    shape = path_distance(foot, jansen_foot) if foot else math.nan
    rows.append({"seed": seed, "fitness": best_f, "shape_distance": shape, "evals": opt.evals, "genome": best})
    print(f"seed {seed:2d} fit {best_f:.3f} shape {shape:.3f} evals {opt.evals}", flush=True)
summary = {
    "params": {"seeds": a.seeds, "evals_per_seed": a.evals, "popsize": a.popsize, "box": "uniform [5,80], start 40, sigma0 22.5"},
    "jansen_flat_fitness": jansen_fit,
    "median_fitness": statistics.median(r["fitness"] for r in rows),
    "beat_jansen": sum(r["fitness"] > jansen_fit for r in rows),
    "median_shape_distance": statistics.median(r["shape_distance"] for r in rows),
    "within_0_05_of_jansen_loop": sum(r["shape_distance"] < 0.05 for r in rows),
}
print(json.dumps(summary, indent=2))
(ROOT / "experiments" / "reproduce-jansen-cmaes.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n")
