"""O-02: fill a MAP-Elites archive over (legs, kinematic stride, mass) and compare it with uniform sampling.

  python packages/opt/scripts/qd_run.py [--evals 20000] [--save-designs data/designs]

Writes experiments/qd-archive.json (every cell with its genome, lineage and fitness, plus the coverage / QD-score curves).
With --save-designs each elite is also written as a design document into that folder, so it shows up in the designer's
"load a saved design" list and opens with one click."""
import argparse
import json
from pathlib import Path

from strandbeest_opt.qd import MapElites, random_search

ROOT = Path(__file__).resolve().parents[3]
ap = argparse.ArgumentParser()
ap.add_argument("--evals", type=int, default=20000)
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--save-designs")
a = ap.parse_args()
base = json.loads((ROOT / "schemas/examples/design-jansen-small-6leg.json").read_text())
qd = MapElites(base, a.seed)
qd.run(a.evals, log_every=500)
rs = random_search(base, a.evals, a.seed)
qd.export(str(ROOT / "experiments" / "qd-archive.json"))
print(f"cells total {qd.cells_total}")
print(f"MAP-Elites : {len(qd.archive):3d} cells ({qd.coverage:.0%}), QD score {sum(e.fitness for e in qd.archive.values()):.1f}, best {max(e.fitness for e in qd.archive.values()):.3f}")
print(f"uniform    : {len(rs.archive):3d} cells ({rs.coverage:.0%}), QD score {sum(e.fitness for e in rs.archive.values()):.1f}, best {max(e.fitness for e in rs.archive.values()):.3f}")
print("curve (evals, cells, QD):", [(e, c, round(q, 1)) for e, c, q in qd.curve[:: max(1, len(qd.curve) // 8)]])
by_legs = {}
for e in qd.archive.values():
    by_legs.setdefault(e.legs, []).append(e)
for legs, es in sorted(by_legs.items()):
    b = max(es, key=lambda e: e.fitness)
    print(f"  {legs:2d} legs: {len(es):2d} cells, best fitness {b.fitness:.3f} (stride {b.stride_m * 100:.0f} cm, mass {b.mass_kg * 1000:.0f} g)")
if a.save_designs:
    out = Path(a.save_designs)
    out.mkdir(parents=True, exist_ok=True)
    for e in qd.archive.values():
        d = qd.design_of(e)
        (out / f"{d['name']}.json").write_text(json.dumps(d, indent=2))
    print("saved", len(qd.archive), "designs to", out)
