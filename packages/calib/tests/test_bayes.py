"""O-04: Bayesian calibration and the identifiability verdict, on a fake simulator with known sensitivities (fast)."""
import math

import numpy as np
import pytest
from strandbeest_calib.bayes import LogParam, build_emulator, infer
from strandbeest_calib.compare import BINS, Curves

PARAMS = [LogParam("strong", 1e4, 1e7, lambda v: {}), LogParam("weak", 0.3, 3.0, lambda v: {}), LogParam("none", 0.5, 2.0, lambda v: {})]
ANGLES = np.linspace(0, 2 * math.pi, BINS, endpoint=False)


def fake_sim(vals):
    """Torque curve: depends strongly on `strong`, weakly on `weak`, not at all on `none`."""
    s = math.log10(vals["strong"]) - 5.5  # -1.5 .. 1.5
    w = math.log(vals["weak"])
    torque = (1.0 + 0.5 * s) * np.sin(ANGLES) + 0.6 * s * np.cos(2 * ANGLES) + 0.03 * w * np.cos(ANGLES) + 0.2 * s**2
    return Curves(torque, 0.28 + 0.01 * s)


def posterior(truth, k=40, noise=0.02, seed=0):
    emu = build_emulator(PARAMS, fake_sim, k, seed=1)
    m = fake_sim(truth)
    rng = np.random.default_rng(seed)
    measured = Curves(m.torque + rng.normal(0, noise, BINS), m.stride)
    return infer(emu, measured, np.full(BINS, noise / 2), n_samples=3000, seed=2), emu


def test_the_strong_parameter_is_recovered_and_the_useless_one_is_flagged_not_identifiable():
    truth = {"strong": 3e5, "weak": 1.0, "none": 1.0}
    post, emu = posterior(truth)
    s = post.summary()
    lo, hi = s["strong"]["posterior_ci95"]
    assert lo < truth["strong"] < hi and hi / lo < 3.0
    assert s["strong"]["identifiable"] is True
    assert s["none"]["identifiable"] is False and s["none"]["profile_share_of_prior"] > 0.6
    # the posterior of a parameter the data know nothing about is the prior (uniform in log): std ratio near 1
    assert 0.6 < s["none"]["posterior_std_over_prior_std"] < 1.2
    assert s["strong"]["posterior_std_over_prior_std"] < 0.2


def test_a_weakly_informed_parameter_gets_a_wide_interval_and_the_summary_is_self_consistent():
    post, _ = posterior({"strong": 3e5, "weak": 1.0, "none": 1.0})
    s = post.summary()
    assert s["weak"]["profile_share_of_prior"] > s["strong"]["profile_share_of_prior"]
    for name, v in s.items():
        a, b = v["profile_ci95"]
        assert a <= v["best"] <= b or math.isclose(v["best"], a, rel=0.05) or math.isclose(v["best"], b, rel=0.05), name
    assert post.chi2_min < 4 * BINS  # the model can fit its own data


def test_the_emulator_error_widens_the_posterior_instead_of_faking_precision():
    truth = {"strong": 3e5, "weak": 1.0, "none": 1.0}
    few, emu_few = posterior(truth, k=10)
    many, emu_many = posterior(truth, k=48)
    assert emu_few.sigma_emu.mean() > emu_many.sigma_emu.mean()
    w = lambda p: np.subtract(*p.summary()["strong"]["profile_ci95"][::-1])
    assert w(few) >= w(many) * 0.9
