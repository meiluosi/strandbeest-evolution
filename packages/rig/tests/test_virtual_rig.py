"""The whole software chain on a simulated rig: raw CSV -> Measurement -> comparison with the run it came from."""

import numpy as np
import pytest

from strandbeest_calib.compare import curves, distance
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_rig import Calibration, convert_raw
from strandbeest_rig.virtual_rig import virtual_raw_csv

DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
CAL = Calibration(counts_per_motor_rev=12, gear_ratio=100, kt_nm_per_a=0.02, idle_current_ma=80, calibrated=True)


@pytest.fixture(scope="module")
def chain():
    raw, track = virtual_raw_csv(DESIGN, CAL, omega=2.0, revolutions=2.5)
    doc = convert_raw(raw, CAL, name="virt", design_id=DESIGN.id, design_name=DESIGN.name, omega_rad_s=2.0, raw_name="virt.csv", track=track)
    return raw, track, doc


def test_raw_csv_has_the_firmware_format(chain):
    raw, _, _ = chain
    assert "t_ms,enc,current_mA,load_raw,wind_pulses,pwm" in raw and raw.startswith("# fw=virtual")


def test_converted_measurement_is_valid_steady_and_has_x(chain):
    _, _, doc = chain
    q = doc["quality"]
    assert q["speed_mean_rad_s"] == pytest.approx(2.0, rel=0.05)
    assert "x" in doc["channels"] and q["time_offset_s"] is not None
    assert abs(q["time_offset_s"]) < 0.3  # simulated clocks agree, so alignment by onset finds a small offset


def test_measurement_matches_the_simulation_it_came_from(chain):
    from strandbeest_sim import run, scenario_from_design

    _, _, doc = chain
    res = run(scenario_from_design(DESIGN, {"drive": {"omega": 2.0}, "run": {"revolutions": 2.5, "settle": 0.5}}))
    sim = curves(res.t, res.psi, res.torque, res.x, skip_rev=0.5)
    ch = doc["channels"]
    meas = curves(np.array(ch["t"]), np.array(ch["psi"]), np.array(ch["torque"]), np.array(ch["x"]), skip_rev=0.5)
    assert distance(meas, sim) < 0.25
    assert meas.stride == pytest.approx(sim.stride, rel=0.1)


def test_firmware_csv_lines_are_readable_by_the_host_parser(tmp_path):
    """Compile the firmware's own formatter and parse what it prints (skipped without a C++ compiler)."""
    import shutil
    import subprocess
    from pathlib import Path

    from strandbeest_rig import parse_raw

    cxx = shutil.which("g++") or shutil.which("clang++")
    if cxx is None:
        pytest.skip("no C++ compiler")
    core = Path(__file__).resolve().parents[3] / "hardware" / "firmware" / "lib" / "rigcore"
    src = tmp_path / "emit.cpp"
    src.write_text(
        '#include <cstdio>\n#include "rigcore.h"\nint main(){ std::puts(rig::kCsvHeader); char b[96];\n'
        "for(int i=0;i<5;i++){ rig::Sample s{(uint32_t)(i*10), i*7-3, true, 100.5f+i, false,0,true,(uint32_t)i,100};"
        ' rig::format_sample(b,sizeof b,s); std::puts(b);} }\n'
    )
    exe = tmp_path / "emit"
    subprocess.run([cxx, "-std=c++17", f"-I{core}", str(src), "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout
    cols, _ = parse_raw(out)
    assert list(cols["t_ms"]) == [0, 10, 20, 30, 40]
    assert list(cols["enc"]) == [-3, 4, 11, 18, 25]
    assert cols["current_mA"][1] == pytest.approx(101.5)
    assert np.isnan(cols["load_raw"]).all() and list(cols["wind_pulses"]) == [0, 1, 2, 3, 4]
