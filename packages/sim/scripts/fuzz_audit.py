"""S-07: audit N random walkers in parallel and record the numbers behind every verdict (EXPERIMENTS section 20 did 16 serially).

The walkers come from the same generator as `strandbeest_sim.skeptic.fuzz` (`random_scenario`), drawn one after the other from
Random(seed), so with seed 1 the first 16 are the walkers of section 20. Overrides (a JSON object of scenario sections, e.g.
'{"solver": {"timestep": 0.00005}}') are applied to every walker; they are how a candidate fix is tried on the same walkers.

Usage: python scripts/fuzz_audit.py out.json N seed [workers] [overrides-json]
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.skeptic import audit, random_scenario


def one(job: tuple[int, dict, dict]) -> dict:
    i, d, ov = job
    res = run(scenario_from_design(Design(d), ov))
    findings = audit(res.scenario, res.metrics, res.series, res.stalled)
    m = res.metrics
    return {
        "case": i,
        "legs": d["walker"]["legs"],
        "terrain": ov.get("terrain", {"kind": "flat"}),
        "loop_open_mm": 1000 * m["max_loop_violation"],
        "penetration_mm": 1000 * m["max_penetration"],
        "energy_residual": m.get("energy_residual_share"),
        "stalled": bool(res.stalled),
        "findings": [f.check for f in findings],
        "run_s": float(res.t[-1]),
    }


def main() -> None:
    out, n, seed = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    extra = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
    base = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())
    rng = random.Random(seed)
    jobs = []
    for i in range(n):
        d, ov = random_scenario(rng, base)
        for sec, vals in extra.items():
            ov.setdefault(sec, {}).update(vals)
        jobs.append((i, d, ov))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(one, jobs))
    json.dump({"seed": seed, "n": n, "overrides": extra, "rows": rows}, out.open("w"), indent=1)
    bad = [r for r in rows if r["findings"]]
    opens = sorted(r["loop_open_mm"] for r in rows)
    res = [abs(r["energy_residual"]) for r in rows if r["energy_residual"] is not None]
    print(f"{n} walkers (seed {seed}, overrides {extra}): {len(bad)} audit failures")
    print(f"loop opening mm: median {statistics.median(opens):.2f}, 90th percentile {opens[int(0.9 * (n - 1))]:.2f}, worst {opens[-1]:.2f}; over 3 mm: {sum(o > 3 for o in opens)}")
    print(f"|energy residual|: median {statistics.median(res):.4f}, worst {max(res):.4f}")
    for r in bad:
        print(f"  case {r['case']}: legs {r['legs']} {r['terrain']['kind']}  open {r['loop_open_mm']:.1f} mm  residual {r['energy_residual']}  {r['findings']}")


if __name__ == "__main__":
    main()
