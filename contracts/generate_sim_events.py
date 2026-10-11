"""Generate contracts/sim-events/cases.json: Python's events and diagnosis for synthetic runs that fire every rule.

The runs are built by hand (arrays, metrics, a scenario), so this is fast and covers branches a real browser run cannot reach yet
(the sail drive, gusts, a NaN stride). packages/sim-web/src/events.test.ts must reproduce events, diagnosis (code, severity,
message text, evidence numbers) and the nominal stride exactly. Run: .venv/bin/python contracts/generate_sim_events.py"""

import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from strandbeest_common import Design
from strandbeest_sim import scenario_from_design
from strandbeest_sim.config import sim_config
from strandbeest_sim.events import detect_events, diagnose, nominal_stride_m

ROOT = Path(__file__).parents[1]
DESIGN = json.loads((ROOT / "schemas" / "examples" / "design-jansen-small-6leg.json").read_text())
OUT = ROOT / "contracts" / "sim-events" / "cases.json"
N = 400
T = np.arange(1, N + 1) * 0.002
LEGS = 6


def walking(slip=None, stall=False, saturate=None, loop_open_at=None, psi_rate=2.0, x_rate=0.07, torque=0.01):
    """arrays of a run: legs touch down in turns; optional slip bursts, torque saturation, an opening loop"""
    psi = np.minimum(T * psi_rate, 6.0) if not stall else np.minimum(T * 0.02, 0.03)
    x = T * x_rate
    normal = np.zeros((N, LEGS))
    slipv = np.zeros((N, LEGS))
    for leg in range(LEGS):
        phase = (np.arange(N) + leg * 40) % 240
        normal[:, leg] = np.where(phase < 140, 0.5 + 0.1 * leg, 0.0)
    if slip:
        for leg, a, b, v in slip:
            slipv[a:b, leg] = v
    tau = np.full(N, torque)
    if saturate:
        for a, b, cap in saturate:
            tau[a:b] = cap
    loop = np.full(N, 0.0004)
    if loop_open_at is not None:
        loop[loop_open_at:] = 0.0123
    return dict(t=T, psi=psi, x=x, z=np.full(N, 0.17), torque=tau, series={"foot_normal": normal, "foot_slip": slipv, "loop_residual": loop})


# name, scenario overrides, run kwargs, metrics, stalled
CASES = [
    ("ok-walking", {}, {}, {"stride_per_rev": 0.2}, False),
    ("start-and-stall", {"terrain": {"kind": "step"}, "drive": {"max_torque": 0.3}}, dict(stall=True, saturate=[(100, 130, 0.3), (200, 215, 0.3), (300, 320, 0.3)]), {"stride_per_rev": 0.01}, True),
    ("blocked-by-step", {"terrain": {"kind": "step"}, "drive": {"max_torque": 0.3}}, dict(saturate=[(100, 130, 0.3), (200, 215, 0.3)]), {"stride_per_rev": 0.01}, False),
    ("torque-limit-too-low-flat", {"drive": {"max_torque": 0.3}}, dict(saturate=[(50, 300, 0.3)]), {"stride_per_rev": 0.02}, False),
    ("torque-limit-short-bursts-ignored", {"drive": {"max_torque": 0.3}}, dict(saturate=[(50, 52, 0.3)]), {"stride_per_rev": 0.2}, False),
    ("slipping", {}, dict(slip=[(0, 20, 140, 0.2), (1, 20, 150, 0.3), (2, 30, 160, 0.2), (3, 20, 140, 0.2), (4, 20, 150, 0.2), (5, 20, 140, 0.2)]), {"stride_per_rev": 0.04}, False),
    ("slip-too-short", {}, dict(slip=[(0, 20, 22, 0.5)]), {"stride_per_rev": 0.2}, False),
    ("loop-open", {}, dict(loop_open_at=250), {"stride_per_rev": 0.2}, False),
    ("deep-sinkage", {}, {}, {"stride_per_rev": 0.2, "max_penetration": 0.011}, False),
    ("slow-unexplained", {}, {}, {"stride_per_rev": 0.02}, False),
    ("nan-stride", {}, {}, {"stride_per_rev": None}, False),
    ("sail-stalled", {"drive": {"kind": "sail"}, "wind": {"speed": 2.0}}, dict(stall=True), {"stride_per_rev": 0.0}, True),
    ("sail-weak", {"drive": {"kind": "sail"}, "wind": {"speed": 4.0}}, dict(psi_rate=0.1), {"stride_per_rev": 0.1}, False),
    ("sail-ok", {"drive": {"kind": "sail"}, "wind": {"speed": 3.0}}, dict(psi_rate=4.0), {"stride_per_rev": 0.2}, False),
    ("gusts", {"drive": {"kind": "sail"}, "wind": {"kind": "gusts", "speed": 3.0, "params": {"period": 0.25, "amplitude": 2.0}}}, dict(psi_rate=4.0), {"stride_per_rev": 0.2}, False),
    ("gusts-defaults", {"drive": {"kind": "sail"}, "wind": {"kind": "gusts", "speed": 3.0}}, dict(psi_rate=4.0), {"stride_per_rev": 0.2}, False),
    ("odd-numbers-rounding", {"walker": {"legs": 5}}, dict(slip=[(0, 10, 200, 0.07)]), {"stride_per_rev": 0.1234567}, False),
]


def tolist(a):
    return np.asarray(a, dtype=float).tolist()


def main() -> None:
    cases = []
    for name, ov, kw, metrics, stalled in CASES:
        sc = sim_config(scenario_from_design(Design(DESIGN), copy.deepcopy(ov)))
        arrays = walking(**kw)
        res = SimpleNamespace(scenario=sc, stalled=stalled, metrics={k: (float("nan") if v is None else v) for k, v in metrics.items()}, **{k: v for k, v in arrays.items() if k != "series"}, series=arrays["series"])
        if name == "empty":
            continue
        ev = detect_events(res)
        dg = diagnose(res, ev)
        cases.append(
            {
                "name": name,
                "design": "schemas/examples/design-jansen-small-6leg.json",
                "config": json.loads(sc.model_dump_json()),
                "result": {"t": tolist(res.t), "psi": tolist(res.psi), "x": tolist(res.x), "torque": tolist(res.torque), "stalled": stalled, "metrics": metrics,
                           "series": {k: tolist(v) for k, v in res.series.items()}},
                "expected": {"events": ev, "diagnosis": dg, "nominal_stride_m": nominal_stride_m(sc)},
            }
        )
    # a run with no samples at all
    sc = sim_config(scenario_from_design(Design(DESIGN), {}))
    res = SimpleNamespace(scenario=sc, stalled=False, metrics={}, t=np.array([]), psi=np.array([]), x=np.array([]), z=np.array([]), torque=np.array([]), series={})
    cases.append({"name": "empty", "design": "schemas/examples/design-jansen-small-6leg.json", "config": json.loads(sc.model_dump_json()),
                  "result": {"t": [], "psi": [], "x": [], "torque": [], "stalled": False, "metrics": {}, "series": {}},
                  "expected": {"events": detect_events(res), "diagnosis": diagnose(res, detect_events(res)), "nominal_stride_m": nominal_stride_m(sc)}})
    codes = sorted({d["code"] for c in cases for d in c["expected"]["diagnosis"]})
    kinds = sorted({e["kind"] for c in cases for e in c["expected"]["events"]})
    print(len(cases), "cases; diagnosis codes:", codes, "; event kinds:", kinds)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"note": "Python events/diagnosis for synthetic runs; regenerate with contracts/generate_sim_events.py", "cases": cases}, separators=(",", ":")) + "\n")
    print(OUT.stat().st_size // 1000, "kB")


if __name__ == "__main__":
    main()
