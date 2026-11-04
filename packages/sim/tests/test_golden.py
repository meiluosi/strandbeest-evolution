"""E4-01/E4-02: golden runs. Scenarios recorded in the flat schema-v1 form with the metrics and a fingerprint of their time series;
every version of the simulator, whatever it is built from (v1 migrated to v2, a different backend structure), must reproduce
them on this platform to 1e-7 relative. See contracts/sim-golden/generate.py. Energy-v2 aligns observations at t_n and records effective step work; runs.json remains the original evidence.
Contact-v3 corrects mass-normalised damping; prior corpora remain unchanged. See EXPERIMENTS §59."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from strandbeest_sim import load_scenario, run

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = json.loads((ROOT / "contracts" / "sim-golden" / "runs-contact-v3.json").read_text())["runs"]
OBSERVATIONS = {r['name']: r for r in json.loads((ROOT/'contracts/sim-golden/observation-v3.json').read_text())['runs']}
RTOL = 1e-7


def close(a, b, what):
    if a is None or b is None:
        assert a is None and (b is None or math.isnan(b)), what
        return
    assert a == pytest.approx(b, rel=RTOL, abs=1e-12), what


def sample(a, n=24):
    a = np.asarray(a, float)
    idx = np.linspace(0, len(a) - 1, n).round().astype(int)
    return [float(a[i]) for i in idx]


@pytest.mark.parametrize("g", GOLDEN, ids=[g["name"] for g in GOLDEN])
def test_run_reproduces_the_golden_record(g):
    res = run(load_scenario(g["scenario"]))  # a flat v1 scenario, migrated to v2 on the way in
    assert bool(res.stalled) == g["stalled"]
    assert len(res.t) == g["n"]
    # Observation-v3 includes every integration step in peak invariants. Keep
    # every old motion/energy assertion; independently checked dense traces
    # supply only the two corrected maxima, without changing the tolerances.
    current = OBSERVATIONS[g['name']]
    expected_metrics = {**g['metrics'], **current['peak_metrics']}
    for k, v in expected_metrics.items():
        close(v, res.metrics.get(k), f"metric {k}")
    assert res.audit_observation == current['audit_observation']
    for k, arr in (("t", res.t), ("psi", res.psi), ("x", res.x), ("z", res.z), ("torque", res.torque)):
        for i, (a, b) in enumerate(zip(g["samples"][k], sample(arr))):
            close(a, b, f"{k}[{i}]")
    if "frames" in g:
        f = res.frames
        assert (len(f["t"]), f["pos"].shape[1], int(f["contact"].sum())) == (g["frames"]["count"], g["frames"]["bodies"], g["frames"]["contact_sum"])
        close(g["frames"]["pos_sum"], float(np.round(f["pos"].astype(np.float64).sum(), 4)), "frame positions")
        assert {"bodies": len(res.scene["bodies"]), "geoms": len(res.scene["geoms"]), "obstacles": len(res.scene["obstacles"])} == g["scene"]
    else:
        assert res.frames is None
