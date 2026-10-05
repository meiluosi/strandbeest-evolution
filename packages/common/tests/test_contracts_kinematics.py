"""Python runner of the kinematics contract corpus (contracts/kinematics/*.json)."""

import json
import math
from pathlib import Path

import pytest

from strandbeest_common import gait_metrics, load_spec, solve_pose

FILES = sorted((Path(__file__).resolve().parents[3] / "contracts" / "kinematics").glob("*.json"))


def test_the_corpus_is_not_empty():
    assert len(FILES) >= 4


@pytest.mark.parametrize("path", FILES, ids=[f.stem for f in FILES])
def test_kinematics_contract(path):
    doc = json.loads(path.read_text())
    spec = load_spec(doc["spec"])
    tol = doc["tolerance"]
    for s in doc["samples"]:
        pose = solve_pose(spec, s["theta"])
        assert pose is not None
        for pid, (x, y) in s["points"].items():
            assert pose[pid] == pytest.approx((x, y), abs=tol["points"]), (path.stem, s["theta"], pid)
        # independent of the recorded numbers: every joint is at the stated distance from its two centres
        for j in spec.joints:
            for c, r in zip(j.centers, j.radii):
                assert math.dist(pose[j.id], pose[c]) == pytest.approx(spec.val(r), abs=1e-9)
        assert math.dist(pose["C"], spec.pivot) == pytest.approx(spec.crank, abs=1e-9)
    g = gait_metrics(spec, samples=doc["gait"]["samples"])
    for key in ("width", "lift", "stroke_length", "duty"):
        assert getattr(g, key) == pytest.approx(doc["gait"][key], abs=tol["gait"]), (path.stem, key)
