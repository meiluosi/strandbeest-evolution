"""S-07 follow-up: where do the 12 failing walkers of the 64-walker audit open their loops, and which knob removes it?"""
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.skeptic import random_scenario

FAILING = [17, 19, 20, 23, 31, 40, 52, 53, 55, 56, 58, 61]
VARIANTS = {
    "baseline": {},
    "dt 0.05 ms": {"solver": {"timestep": 0.00005}},
    "solref 0.5 ms": {"solver": {"solref_time": 0.0005}},
    "torque cap 0.15": {"drive": {"max_torque": 0.15}},
    "omega 1.0": {"drive": {"omega": 1.0}},
}


def one(job):
    i, d, ov, name, extra = job
    ov = {k: dict(v) for k, v in ov.items()}
    for sec, vals in extra.items():
        ov.setdefault(sec, {}).update(vals)
    ov.setdefault("run", {}).update({"frame_rate": 100})
    res = run(scenario_from_design(Design(d), ov))
    lr = res.series["loop_residual"]
    k = int(np.argmax(lr))
    t_open = float(res.t[k])
    fr = res.frames
    j = int(np.argmin(np.abs(fr["t"] - t_open)))
    feet_down = int(fr["contact"][j].sum())
    cap = res.scenario.drive.max_torque
    return {"case": i, "variant": name, "open_mm": 1000 * float(lr.max()), "t_open": t_open,
            "feet_down": feet_down, "legs": d["walker"]["legs"], "torque_at_open": float(res.torque[k]),
            "cap": cap, "terrain": ov.get("terrain", {}).get("kind", "flat")}


def main():
    base = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())
    rng = random.Random(1)
    cases = {}
    for i in range(64):
        cases[i] = random_scenario(rng, base)
    jobs = [(i, *cases[i], name, extra) for name, extra in VARIANTS.items() for i in FAILING]
    with ProcessPoolExecutor(max_workers=int(sys.argv[2])) as ex:
        rows = list(ex.map(one, jobs))
    json.dump(rows, open(sys.argv[1], "w"), indent=1)
    for name in VARIANTS:
        r = [x for x in rows if x["variant"] == name]
        print(f"{name:16s} over 3 mm: {sum(x['open_mm'] > 3 for x in r):2d}/12  median {np.median([x['open_mm'] for x in r]):.2f}  worst {max(x['open_mm'] for x in r):.2f}")
    print("baseline detail (case, legs, terrain, open mm, t, feet down, torque/cap):")
    for x in rows[:12]:
        print(f"  {x['case']:2d} {x['legs']} {x['terrain']:6s} {x['open_mm']:5.1f} t={x['t_open']:.2f} down={x['feet_down']} tq={x['torque_at_open']:.3f}/{x['cap']}")


if __name__ == "__main__":
    main()
