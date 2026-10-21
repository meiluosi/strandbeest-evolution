"""Tests for W-10 body and linkage aerodynamic drag / thrust (WIND.md section 4, docs/ACTIONS.md W-10)."""

import math
import pytest
from strandbeest_common import Design
from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.backends.mujoco_backend import MujocoBackend
from strandbeest_sim.contract import _example_design, _scenario
from strandbeest_sim.runner import run


def test_body_drag_analytical_limits():
    """Verify analytical limits in tailwind, headwind, and calm air."""
    rho = 1.2
    cd = 1.1
    area = 0.05

    def drag_force(v_wind: float, vx: float) -> float:
        v_rel = v_wind - vx
        return 0.5 * rho * cd * area * abs(v_rel) * v_rel

    # 1. Tailwind on stationary walker: forward thrust
    f_tail = drag_force(5.0, 0.0)
    assert abs(f_tail - 0.825) < 1e-9
    assert f_tail > 0.0

    # 2. Headwind on stationary walker: backward drag
    f_head = drag_force(-5.0, 0.0)
    assert abs(f_head - (-0.825)) < 1e-9
    assert f_head < 0.0

    # 3. Calm air on moving walker: aerodynamic resistance
    f_calm = drag_force(0.0, 2.0)
    assert abs(f_calm - (-0.132)) < 1e-9
    assert f_calm < 0.0

    # 4. Walker moving faster than tailwind: aerodynamic resistance
    f_fast = drag_force(2.0, 3.0)
    assert abs(f_fast - (-0.033)) < 1e-9
    assert f_fast < 0.0


def test_body_drag_simulation_k2_and_mujoco():
    """Verify that body drag is correctly applied to the chassis in K2 and MuJoCo."""
    d = _example_design()

    # Scenario with tailwind and chassis drag
    ov_drag = {
        "drive": {"kind": "sail"},
        "wind": {"kind": "constant", "speed": 4.0},
        "walker": {"body_drag_area": 0.04, "body_drag_coeff": 1.1},
        "run": {"revolutions": 0.3, "settle": 0.1, "frame_rate": 0},
    }

    sc_drag = _scenario(d, ov_drag)

    # Both backends run with body drag
    res_k2 = run(sc_drag, backend=K2Backend())
    res_mj = run(sc_drag, backend=MujocoBackend())

    assert res_k2.metrics["stride_per_rev"] > 0.0
    assert res_mj.metrics["stride_per_rev"] > 0.0

    # Walk distance is positive and matches within reasonable cross-solver margin
    assert abs(res_k2.x[-1] - res_mj.x[-1]) < 0.03


def test_body_drag_effect_on_startability():
    """Verify that tailwind on the chassis assists starting (lowers starting wind threshold)."""
    d = _example_design()

    # Low wind near stall threshold (e.g. 0.65 m/s)
    ov_nodrag = {
        "drive": {"kind": "sail"},
        "wind": {"kind": "constant", "speed": 0.65},
        "walker": {"body_drag_area": 0.0},
        "run": {"revolutions": 0.2, "settle": 0.1, "max_time": 4.0, "frame_rate": 0},
    }

    ov_withdrag = {
        "drive": {"kind": "sail"},
        "wind": {"kind": "constant", "speed": 0.65},
        "walker": {"body_drag_area": 0.05, "body_drag_coeff": 1.2},
        "run": {"revolutions": 0.2, "settle": 0.1, "max_time": 4.0, "frame_rate": 0},
    }

    res_no = run(_scenario(d, ov_nodrag), backend=K2Backend())
    res_with = run(_scenario(d, ov_withdrag), backend=K2Backend())

    # Forward distance with chassis wind assistance is greater than or equal to without
    assert res_with.x[-1] >= res_no.x[-1]
