import json
import math

import numpy as np
import pytest

from strandbeest_rig import Calibration, convert_raw, fit_torque_from_hanging_masses, parse_raw

DESIGN_ID = "0000000000YNGRWX0MDFYPZHXT"
CAL = Calibration(counts_per_motor_rev=12, gear_ratio=100, kt_nm_per_a=0.5, idle_current_ma=100, calibrated=True)


def raw(seconds=12.0, rate=100, omega=2.0, direction=1, torque_fn=lambda psi: 0.05 + 0.02 * math.sin(psi), t0_ms=0, extra_header=""):
    lines = [extra_header + "# fw=test-1.0", "t_ms,enc,current_mA,load_raw,wind_pulses,pwm"]
    for i in range(int(seconds * rate)):
        t = i / rate
        psi = omega * t
        enc = round(direction * psi / (2 * math.pi) * CAL.gear_ratio * CAL.counts_per_motor_rev)
        cur = CAL.idle_current_ma + torque_fn(psi) / CAL.kt_nm_per_a * 1000
        lines.append(f"{int(t * 1000) + t0_ms},{enc},{cur:.1f},,,")
    return "\n".join(lines) + "\n"


def convert(text, **kw):
    return convert_raw(text, kw.pop("cal", CAL), name="t1", design_id=DESIGN_ID, design_name="d", omega_rad_s=kw.pop("omega", 2.0), **kw)


def test_angle_and_torque_come_out_in_physical_units():
    doc = convert(raw())
    t, psi, tq = (np.array(doc["channels"][k]) for k in ("t", "psi", "torque"))
    assert psi[-1] / t[-1] == pytest.approx(2.0, rel=0.01)
    assert tq == pytest.approx(0.05 + 0.02 * np.sin(psi), abs=0.002)
    assert doc["provenance"]["source"] == "rig" and doc["provenance"]["rig_version"] == "test-1.0"
    assert doc["synthetic"] is False


def test_quality_report_measures_rate_revolutions_and_steadiness():
    q = convert(raw())["quality"]
    assert q["sample_rate_hz"] == pytest.approx(100, rel=0.02)
    assert q["revolutions"] == pytest.approx(12 * 2 / (2 * math.pi), rel=0.02)
    assert q["speed_cv"] < 0.05 and q["dropouts"] == 0
    assert q["warnings"] == []  # calibrated, long enough, steady


def test_warnings_for_a_wrong_direction_short_run_and_missing_calibration():
    q = convert(raw(direction=-1))["quality"]
    assert any("direction" in w for w in q["warnings"])
    q = convert(raw(seconds=2.0))["quality"]
    assert any("revolutions" in w for w in q["warnings"])
    q = convert(raw(), cal=Calibration(counts_per_motor_rev=12, gear_ratio=100, idle_current_ma=100))["quality"]
    assert any("not marked as calibrated" in w for w in q["warnings"])
    q = convert(raw(), omega=3.0)["quality"]
    assert any("differs from the stated" in w for w in q["warnings"])


def test_dropouts_are_counted_and_truncated_lines_are_skipped():
    lines = raw().splitlines()
    del lines[300:330]  # a 0.3 s gap
    lines.insert(50, "12345,6")  # truncated serial line
    q = convert("\n".join(lines) + "\n")["quality"]
    assert q["dropouts"] >= 1


def test_millisecond_counter_wrap_is_unwrapped():
    start = 2**32 - 3000
    doc = convert(raw(t0_ms=start))
    t = np.array(doc["channels"]["t"])
    assert np.all(np.diff(t) > 0) and t[-1] == pytest.approx(11.99, abs=0.05)


def test_missing_required_columns_is_a_clear_error():
    with pytest.raises(ValueError, match="missing required columns"):
        parse_raw("a,b\n1,2\n")
    with pytest.raises(ValueError, match="no data rows"):
        parse_raw("t_ms,enc\n")


def test_load_cell_torque_path():
    cal = Calibration(counts_per_motor_rev=12, gear_ratio=100, torque_method="load_cell", arm_m=0.1, counts_per_gram=100.0, zero_counts=500, calibrated=True)
    lines = ["t_ms,enc,current_mA,load_raw"]
    for i in range(1200):
        lines.append(f"{i * 10},{i * 20},,{500 + 100 * 50.0}")  # 50 g on a 0.1 m arm
    doc = convert_raw("\n".join(lines) + "\n", cal, name="lc", design_id=DESIGN_ID, design_name="d")
    assert np.mean(doc["channels"]["torque"]) == pytest.approx(0.05 * 9.80665 * 0.1, rel=1e-3)


def test_hanging_mass_calibration_recovers_the_torque_constant():
    kt, i0, arm = 0.8, 120.0, 0.05
    masses = [20, 50, 100, 150, 200, 300]
    rng = np.random.default_rng(0)
    currents = [i0 + m * 1e-3 * 9.80665 * arm / kt * 1000 + rng.normal(0, 2) for m in masses]
    fit = fit_torque_from_hanging_masses(masses, currents, arm)
    assert fit.kt_nm_per_a == pytest.approx(kt, rel=0.03)
    assert fit.idle_current_ma == pytest.approx(i0, abs=8)
    with pytest.raises(ValueError):
        fit_torque_from_hanging_masses([10, 20], [1, 2], arm)
    with pytest.raises(ValueError, match="non-positive"):
        fit_torque_from_hanging_masses([10, 20, 30], [300, 200, 100], arm)
