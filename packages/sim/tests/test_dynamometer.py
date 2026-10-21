"""Tests for W-06 Virtual Dynamometer (docs/WIND.md section 5, docs/ACTIONS.md W-06)."""

import math
from strandbeest_common import Design
from strandbeest_sim.contract import _example_design
from strandbeest_sim.dynamometer import virtual_dynamometer


def test_virtual_dynamometer_quasi_static():
    d = Design(_example_design())
    res = virtual_dynamometer(d, samples=90)

    assert len(res["theta"]) == 90
    assert len(res["theta_deg"]) == 90
    assert len(res["torque_quasi"]) == 90
    assert len(res["torque_sail"]) == 90
    assert len(res["margin"]) == 90

    # The peak torque is positive
    assert res["peak_torque"] > 0.0
    assert 0.0 <= res["stall_angle_deg"] < 360.0
    assert res["min_start_wind"] > 0.0

    # At the minimum start wind, margin at the stall angle is approximately zero
    res_crit = virtual_dynamometer(d, wind_speed=res["min_start_wind"], samples=90)
    assert abs(res_crit["stall_margin"]) < 1e-4

    # Below min_start_wind, the sail stalls
    res_low = virtual_dynamometer(d, wind_speed=res["min_start_wind"] * 0.8, samples=90)
    assert res_low["stalls"] is True
    assert res_low["stall_margin"] < 0.0

    # Above min_start_wind, the sail does not stall
    res_high = virtual_dynamometer(d, wind_speed=res["min_start_wind"] * 1.2, samples=90)
    assert res_high["stalls"] is False
    assert res_high["stall_margin"] > 0.0


def test_virtual_dynamometer_with_simulation():
    d = Design(_example_design())
    res = virtual_dynamometer(d, samples=60, with_simulation=True, backend="k2")

    assert "torque_sim" in res
    assert len(res["torque_sim"]) == 60
    assert res["sim_peak_torque"] > 0.0
