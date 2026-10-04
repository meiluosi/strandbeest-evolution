"""Cross-check the MuJoCo simulator against the reduced-order (quasi-static) model in the slow-crank limit.

Usage:  python scripts/crosscheck.py '<scenario overrides as JSON>' tag
Runs a 3-revolution slow flat-ground drive (cached in $TMPDIR/var_<tag>.npz), then compares stride and the crank-torque
curve against tests/data/reference-flat.json (regenerate with `pnpm sim:reference` at the repo root).
The reference gets a leg-gravity term added because MuJoCo's legs have mass and the reduced-order model's do not.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

from strandbeest_sim import load_scenario, run
from strandbeest_sim.builder import resolve_spec
from strandbeest_sim.linkage import solve_pose

ROOT = Path(__file__).parents[1]
BASE = {
    "walker": {"legs": 12, "pitch": "locked", "mass": 50, "tube_mass_per_m": 0.12},
    "drive": {"omega": 0.6, "ramp": 2},
    "run": {"revolutions": 3, "settle": 1.0, "record_every": 4},
}


def merge(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if isinstance(v, dict):
            merge(a.setdefault(k, {}), v)
        else:
            a[k] = v
    return a


def reference(sc, ref: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    spec = resolve_spec(sc)
    u, n, dirn, g = sc.walker.unit, sc.walker.legs, sc.walker.direction, 9.81
    psi = np.array([s["psi"] for s in ref["samples"]])
    tau_ts = np.array([s["torque"] for s in ref["samples"]])
    bars = [
        (c, j.id, max(sc.walker.tube_mass_per_m * spec.val(r) * u, sc.walker.min_bar_mass))
        for j in spec.joints
        for c, r in zip(j.centers, j.radii)
    ]
    mc = max(sc.walker.tube_mass_per_m * spec.crank * u, sc.walker.min_bar_mass)

    def leg_height_sum(p: float) -> float:
        s = 0.0
        for i in range(n):
            pose = solve_pose(spec, dirn * p + 2 * math.pi * i / n)
            s += sum(m * 0.5 * (pose[a][1] + pose[b][1]) * u for a, b, m in bars)
            s += mc * 0.5 * (spec.pivot[1] + pose["C"][1]) * u
        return s

    h = 1e-4
    leg = np.array([g * (leg_height_sum(p + h) - leg_height_sum(p - h)) / (2 * h) for p in psi])
    return psi, tau_ts, tau_ts + leg


def main() -> None:
    overrides = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    tag = sys.argv[2] if len(sys.argv) > 2 else "default"
    sc_dict = merge(json.loads(json.dumps(BASE)), overrides)
    sc = load_scenario(sc_dict)
    cache = Path(os.environ.get("TMPDIR", tempfile.gettempdir())) / f"var_{tag}.npz"
    if cache.exists():
        d = np.load(cache)
        stride = float("nan")
    else:
        res = run(sc)
        np.savez(cache, t=res.t, psi=res.psi, x=res.x, z=res.z, tau=res.torque)
        d = np.load(cache)
        stride = res.metrics.get("stride_per_rev", float("nan"))
    ref = json.loads((ROOT / "tests/data/reference-flat.json").read_text())
    psi_ref, tau_ts, tau_ref = reference(sc, ref)
    mask = d["psi"] > 2 * math.pi
    bins = np.linspace(0, 2 * math.pi, 73)
    idx = np.digitize(np.mod(d["psi"][mask], 2 * math.pi), bins) - 1
    tau_mj = np.array([d["tau"][mask][idx == k].mean() if (idx == k).any() else np.nan for k in range(72)])
    centers = 0.5 * (bins[:-1] + bins[1:])
    ok = ~np.isnan(tau_mj)
    r = np.interp(centers, psi_ref, tau_ref)
    corr = float(np.corrcoef(tau_mj[ok], r[ok])[0, 1])
    print(
        json.dumps(
            {
                "tag": tag,
                "stride_mujoco": stride,
                "stride_reference": ref["stride"],
                "torque_mean_mujoco": float(np.nanmean(tau_mj)),
                "torque_mean_reference": float(r.mean()),
                "torque_ptp_mujoco": float(np.ptp(tau_mj[ok])),
                "torque_ptp_reference": float(np.ptp(r)),
                "torque_curve_correlation": corr,
            }
        )
    )


if __name__ == "__main__":
    main()
