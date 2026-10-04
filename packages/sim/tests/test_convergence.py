"""Numerical convergence at fixed physical settings (slow: each case is a short walk). Run with -m slow."""

import pytest

from strandbeest_sim import load_scenario, run

pytestmark = pytest.mark.slow

BASE = {
    "walker": {"legs": 12, "pitch": "locked", "tube_mass_per_m": 0.12},
    "drive": {"omega": 0.6, "ramp": 2},
    "run": {"revolutions": 1.8, "settle": 1.0, "record_every": 8},
}


def metrics(**solver):
    cfg = {**BASE, "solver": solver}
    return run(load_scenario(cfg)).metrics


def test_stride_and_mean_torque_do_not_depend_on_timestep():
    a, b = metrics(timestep=5e-4), metrics(timestep=2.5e-4)
    assert a["stride_per_rev"] == pytest.approx(b["stride_per_rev"], rel=0.01)
    assert a["mean_torque"] == pytest.approx(b["mean_torque"], rel=0.02)


def test_loop_constraints_stay_closed_with_the_default_settings():
    assert metrics()["max_loop_violation"] < 1e-3


def test_solver_iterations_have_converged():
    a, b = metrics(iterations=30), metrics(iterations=300)
    assert a["mean_torque"] == pytest.approx(b["mean_torque"], rel=0.01)
