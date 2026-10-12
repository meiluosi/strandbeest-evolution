"""Generate contracts/sim-run/cases.json: short Python runs (settle + a fraction of a revolution) with everything the browser
preview records, unrounded: the crank series, the replay frames (poses, foot contacts, loads, centre of mass), the replay scene
and the gait metrics. packages/sim-web runs the same scenarios on MuJoCo WebAssembly and must follow these to rounding.

Run from the repo root with the packages on the path:
  PYTHONPATH=packages/common/src:packages/sim/src ../strandbeest-evolution/.venv/bin/python contracts/generate_sim_run.py"""

import copy
import json
from pathlib import Path

import numpy as np

from strandbeest_common import Design
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.events import detect_events, diagnose

ROOT = Path(__file__).parents[1]
DESIGN = "schemas/examples/design-jansen-small-6leg.json"
OUT = ROOT / "contracts" / "sim-run" / "cases.json"

CASES = [
    ("flat", {"run": {"revolutions": 0.15, "frame_rate": 30}}),
    # a step the first swing feet reach: the contact list is not empty and a foot is blocked
    ("step", {"terrain": {"kind": "step", "params": {"distance": 0.03, "height": 0.006}}, "run": {"revolutions": 0.2, "frame_rate": 30}}),
    ("slope", {"terrain": {"kind": "slope", "slope_deg": 8.0}, "run": {"revolutions": 0.12, "frame_rate": 30}}),
    ("soft", {"terrain": {"kind": "soft", "params": {"stiffness": 5000.0, "damping": 90.0}}, "run": {"revolutions": 0.12, "frame_rate": 30}}),
    # audit cases (no frames): each one makes the rules of events.py fire
    ("audit-blocked-step", {"terrain": {"kind": "step", "params": {"distance": 0.02, "height": 0.03}}, "run": {"revolutions": 1, "max_time": 3, "frame_rate": 0}}),
    ("audit-torque-limit", {"drive": {"max_torque": 0.0004}, "run": {"revolutions": 0.5, "max_time": 3, "frame_rate": 0}}),
    ("audit-soft-sinkage", {"solver": {"contact_stiffness": 1500.0}, "run": {"revolutions": 0.2, "frame_rate": 0}}),
    ("audit-loose-loops", {"solver": {"iterations": 3, "solref_time": 0.05, "timestep": 0.0005}, "run": {"revolutions": 0.15, "frame_rate": 0}}),
    # the sail drive in the three winds (the web player runs it as scenes wind / gusts), and a sail that cannot start
    ("sail-wind", {"drive": {"kind": "sail"}, "wind": {"speed": 3.0}, "run": {"revolutions": 0.3, "max_time": 10, "give_up_after": 6, "frame_rate": 30}}),
    ("sail-gusts", {"drive": {"kind": "sail"}, "wind": {"kind": "gusts", "speed": 3.0, "params": {"period": 2.0, "amplitude": 1.5}}, "run": {"revolutions": 0.3, "max_time": 10, "give_up_after": 6, "frame_rate": 0}}),
    ("sail-lull", {"drive": {"kind": "sail"}, "wind": {"kind": "lull", "speed": 4.0, "params": {"at": 1.2}}, "run": {"revolutions": 0.6, "max_time": 6, "give_up_after": 3, "frame_rate": 0}}),
    ("sail-calm-stall", {"drive": {"kind": "sail"}, "wind": {"speed": 0.5}, "run": {"revolutions": 0.5, "max_time": 8, "give_up_after": 3, "frame_rate": 0}}),
]


def lists(a):
    return np.asarray(a, dtype=float).tolist()


def one(overrides):
    design = Design.load(ROOT / DESIGN)
    res = run(scenario_from_design(design, copy.deepcopy(overrides)))
    f = res.frames
    s = res.scene
    metrics = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in res.metrics.items()}
    events = detect_events(res)
    diagnosis = diagnose(res, events)
    sstep = max(1, len(res.t) // 500)  # the replay endpoint's decimation of the energy series (apps/api app.py)
    energy = {k: np.round(np.asarray(v if k != "t" else res.t)[::sstep], 7).tolist() for k, v in {**{"t": res.t}, **{k: res.series[k] for k in ("e_in", "e_contact", "e_loops", "e_friction", "kinetic", "potential", "loop_residual", "penetration")}}.items()}
    return {
        "series": {"t": lists(res.t), "psi": lists(res.psi), "x": lists(res.x), "torque": lists(res.torque)},
        "frames": None if f is None else {k: lists(f[k]) for k in ("t", "pos", "quat", "foot_pos", "foot_force", "foot_slip", "com")} | {"contact": np.asarray(f["contact"], dtype=int).tolist()},
        "scene": s,
        "metrics": metrics,
        "events": events,
        "diagnosis": diagnosis,
        "energy": energy,
        "stalled": bool(res.stalled),
    }


def main() -> None:
    """With names: regenerate only those cases and merge them into the existing file; without: all."""
    import sys

    names = sys.argv[1:]
    old = json.loads(OUT.read_text())["cases"] if OUT.exists() else []
    kept = {c["name"]: c for c in old}
    for n, ov in CASES:
        if names and n not in names:
            continue
        c = {"name": n, "design": DESIGN, "overrides": ov, "expected": one(ov)}
        e = c["expected"]
        print(n, len(e["series"]["t"]), "samples", len(e["frames"]["t"]) if e["frames"] else 0, "frames", "diagnosis", [d["code"] for d in e["diagnosis"]], "events", sorted({x["kind"] for x in e["events"]}), "wind_only", e["metrics"].get("wind_only"), flush=True)
        kept[n] = c
    cases = [kept[n] for n, _ in CASES if n in kept]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"note": "Python runs for packages/sim-web/src/run.test.ts; regenerate with contracts/generate_sim_run.py [case ...]", "cases": cases}, separators=(",", ":")) + "\n")
    print(OUT.stat().st_size // 1000, "kB")


if __name__ == "__main__":
    main()
