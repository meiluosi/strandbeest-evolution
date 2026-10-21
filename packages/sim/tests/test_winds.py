"""Tests for W-04 Wind Field v2: shear profiles, turbulence, and yaw angles."""

import math
import numpy as np
import pytest
from strandbeest_sim.config import Wind
from strandbeest_sim.winds import constant, gusts, lull, profile_turbulent, shear, turbulent


def test_constant_with_yaw():
    w = Wind(kind="constant", speed=5.0, params={"yaw_deg": 60.0})
    f = constant(w)
    # cos(60 deg) = 0.5
    assert abs(f(0.0) - 2.5) < 1e-6
    assert abs(f(10.0) - 2.5) < 1e-6

    # Crosswind (90 deg) -> zero forward drive
    w_cross = Wind(kind="constant", speed=5.0, params={"yaw_deg": 90.0})
    f_cross = constant(w_cross)
    assert abs(f_cross(0.0)) < 1e-6


def test_gusts_and_lull():
    w_g = Wind(kind="gusts", speed=4.0, params={"amplitude": 2.0, "period": 4.0})
    f_g = gusts(w_g)
    assert abs(f_g(0.0) - 4.0) < 1e-6
    assert abs(f_g(1.0) - 6.0) < 1e-6  # crest
    assert abs(f_g(3.0) - 2.0) < 1e-6  # trough

    w_l = Wind(kind="lull", speed=3.0, params={"at": 5.0})
    f_l = lull(w_l)
    assert f_l(0.0) == 3.0
    assert f_l(4.99) == 3.0
    assert f_l(5.01) == 0.0


def test_shear_power_law():
    w = Wind(kind="shear", speed=10.0, params={"z_ref": 1.0, "alpha": 0.14, "profile": "power"})
    f = shear(w)

    # At z_ref, factor is 1.0
    assert abs(f(0.0, 1.0) - 10.0) < 1e-6
    # When z is omitted, defaults to z_ref
    assert abs(f(0.0) - 10.0) < 1e-6

    # Lower height z=0.2 m -> (0.2)^0.14 = 0.79919
    v_low = f(0.0, 0.2)
    expected_low = 10.0 * (0.2**0.14)
    assert abs(v_low - expected_low) < 1e-5

    # Higher height z=2.0 m -> (2.0)^0.14 = 1.1019
    v_high = f(0.0, 2.0)
    expected_high = 10.0 * (2.0**0.14)
    assert abs(v_high - expected_high) < 1e-5


def test_shear_log_profile():
    w = Wind(kind="shear", speed=10.0, params={"z_ref": 1.0, "z_0": 0.001, "profile": "log"})
    f = shear(w)
    assert abs(f(0.0, 1.0) - 10.0) < 1e-6

    # z = 0.1 m: ln(0.1/0.001) / ln(1.0/0.001) = ln(100) / ln(1000) = 2/3
    v_log = f(0.0, 0.1)
    assert abs(v_log - 10.0 * (2.0 / 3.0)) < 1e-4


def test_turbulent_determinism():
    w1 = Wind(kind="turbulent", speed=6.0, params={"seed": 42})
    w2 = Wind(kind="turbulent", speed=6.0, params={"seed": 42})
    w3 = Wind(kind="turbulent", speed=6.0, params={"seed": 43})

    f1 = turbulent(w1)
    f2 = turbulent(w2)
    f3 = turbulent(w3)

    t_eval = [0.0, 0.5, 1.0, 5.0, 10.0, 25.0]
    vals1 = [f1(t) for t in t_eval]
    vals2 = [f2(t) for t in t_eval]
    vals3 = [f3(t) for t in t_eval]

    # Deterministic for the same seed
    assert vals1 == vals2
    # Different for different seed
    assert vals1 != vals3


def test_turbulent_statistics():
    """Verify statistical properties of the Dryden/Ornstein-Uhlenbeck turbulence process."""
    speed = 5.0
    intensity = 0.15
    integral_length = 25.0
    tau = integral_length / speed  # 5.0 s
    sigma = intensity * speed  # 0.75 m/s

    w = Wind(
        kind="turbulent",
        speed=speed,
        params={
            "intensity": intensity,
            "integral_length": integral_length,
            "seed": 1234,
            "dt": 0.05,
        },
    )
    f = turbulent(w)

    duration = 300.0
    dt_eval = 0.05
    n_pts = int(duration / dt_eval)
    t_series = [i * dt_eval for i in range(n_pts)]
    v_series = np.array([f(t) for t in t_series])

    # Sample mean close to speed 5.0 m/s (within 0.25 m/s)
    mean_v = np.mean(v_series)
    assert abs(mean_v - speed) < 0.25, f"mean {mean_v:.3f} deviates from {speed}"

    # Sample standard deviation close to sigma = 0.75 m/s (within 15%)
    std_v = np.std(v_series)
    assert abs(std_v - sigma) / sigma < 0.15, f"std {std_v:.3f} deviates from {sigma:.3f}"

    # Autocorrelation decay test
    fluct = v_series - mean_v
    var_0 = np.mean(fluct**2)

    for lag_sec in [2.0, 5.0, 10.0]:
        lag_idx = int(lag_sec / dt_eval)
        cov_lag = np.mean(fluct[:-lag_idx] * fluct[lag_idx:])
        r_sample = cov_lag / var_0
        r_theory = math.exp(-lag_sec / tau)
        # Sample autocorrelation within 0.15 of theoretical exponential decay
        assert (
            abs(r_sample - r_theory) < 0.15
        ), f"Autocorrelation at lag {lag_sec}s: sample {r_sample:.3f} vs theory {r_theory:.3f}"


def test_profile_turbulent():
    w = Wind(
        kind="profile_turbulent",
        speed=6.0,
        params={
            "z_ref": 1.0,
            "alpha": 0.14,
            "intensity": 0.10,
            "seed": 99,
            "yaw_deg": 30.0,
        },
    )
    f = profile_turbulent(w)

    # Evaluates stably across heights and times
    v_ground = f(1.0, 0.1)
    v_hub = f(1.0, 1.0)
    v_high = f(1.0, 2.0)

    # Average trend: wind increases with height
    assert v_high > v_ground
