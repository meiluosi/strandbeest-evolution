"""O-04: Bayesian calibration of contact stiffness, friction and leg mass from SYNTHETIC torque data (no real measurement exists).

  python packages/calib/scripts/bayes_study.py [--points 32] [--noise 0.03]  -> experiments/bayes-calibration-synthetic.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
from strandbeest_calib.bayes import LogParam, build_emulator, infer, noise_from_data  # noqa: E402
from strandbeest_calib.calibrate import _merge  # noqa: E402
from strandbeest_calib.compare import curves  # noqa: E402
from strandbeest_common import Design  # noqa: E402
from strandbeest_sim import run, scenario_from_design  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--points", type=int, default=32)
ap.add_argument("--noise", type=float, default=0.03)
ap.add_argument("--floor", type=float, default=0.01, help="noise floor as a share of mean |torque|")
ap.add_argument("--known-noise", action="store_true", help="use the synthetic noise level itself (standard error of a bin mean) instead of estimating it from the data")
ap.add_argument("--out", default="bayes-calibration-synthetic.json")
a = ap.parse_args()

design = Design.load(ROOT / "schemas/examples/design-jansen-small-6leg.json")
nominal_mass = design.bar_mass_per_m()
PARAMS = [
    LogParam("contact_stiffness", 1e4, 1e7, lambda v: {"solver": {"contact_stiffness": v}}),
    LogParam("friction", 0.3, 3.0, lambda v: {"walker": {"foot_friction": v}, "terrain": {"friction": v}}),
    LogParam("leg_mass_per_m", 0.5 * nominal_mass, 2.0 * nominal_mass, lambda v: {"walker": {"tube_mass_per_m": v}}),
]
BY = {p.name: p for p in PARAMS}
RUN = {"run": {"revolutions": 2.2, "settle": 0.4, "frame_rate": 0}}


def overrides(vals, extra=None):
    ov = json.loads(json.dumps(RUN))
    for k, v in vals.items():
        _merge(ov, BY[k].apply(v))
    return _merge(ov, extra or {})


def simulate(vals):
    res = run(scenario_from_design(design, overrides(vals)))
    return curves(res.t, res.psi, res.torque, res.x, 0.5)


truth = {"contact_stiffness": 2e5, "friction": 1.2, "leg_mass_per_m": nominal_mass * 1.0}
print("truth", truth, flush=True)
res = run(scenario_from_design(design, overrides(truth, {"run": {"revolutions": 4.5}})))
rng = np.random.default_rng(7)
tq = res.torque + rng.normal(0, a.noise * float(np.mean(np.abs(res.torque))), res.torque.shape)
measured = curves(res.t, res.psi, tq, res.x, 0.5)
sigma = noise_from_data(res.t, res.psi, tq, floor_share=a.floor)
if a.known_noise:
    n_per_bin = float((res.psi >= res.psi[0] + 0.5 * 2 * np.pi).sum()) / 36
    sigma = np.full(36, a.noise * float(np.mean(np.abs(res.torque))) / np.sqrt(n_per_bin))
print('noise sigma used (mean over bins, N*m):', float(np.mean(sigma)), 'estimated from data:', float(np.mean(noise_from_data(res.t, res.psi, tq, floor_share=a.floor))), flush=True)
emu = build_emulator(PARAMS, simulate, a.points, seed=1, progress=lambda i, k: print(f"emulator run {i}/{k}", flush=True))
post = infer(emu, measured, sigma)
summary = post.summary()
print(json.dumps(summary, indent=1))
tq_sig = np.nanstd(emu.y[:, :36], axis=0)
print("torque signal across the box (mean over bins, std):", float(np.mean(tq_sig)), "| emulator LOO RMS on the torque bins:", float(np.mean(emu.sigma_emu[:36])), "| data sigma:", float(np.mean(sigma)), flush=True)
print("chi2 at the best fit:", post.chi2_min, "for", 36, "torque bins + stride; emulator LOO error (mean over features):", float(emu.sigma_emu.mean()))
(ROOT / "experiments" / a.out).write_text(json.dumps({"truth": truth, "noise": a.noise, "floor": a.floor, "points": a.points, "summary": summary, "chi2_min": post.chi2_min, "emulator_loo_rms_mean": float(emu.sigma_emu.mean()), "torque_signal_std": float(np.mean(tq_sig)), "emulator_loo_torque": float(np.mean(emu.sigma_emu[:36])), "data_sigma": float(np.mean(sigma)), "synthetic": True}, indent=1) + "\n")
