"""Generate contracts/kinematics/*.json. Run: python contracts/generate_kinematics.py (uses the Python solver)."""

import json
import math
from pathlib import Path

from strandbeest_common import load_spec, solve_pose
from strandbeest_common.gait import gait_metrics

OUT = Path(__file__).parent / "kinematics"
J = json.loads((Path(__file__).parents[1] / "schemas" / "examples" / "design-jansen-small-6leg.json").read_text())["linkage"]

DESIGNS = {
    "jansen": J,
    # crank-rocker four-bar: the rocker pivots at G, the coupler joins C and K; the foot is the coupler/rocker joint K
    "fourbar-crank-rocker": {
        "params": {"a": 40.0, "l": 0.0, "m": 10.0, "b": 45.0, "j": 38.0},
        "crank": {"x": "a", "y": "l", "length": "m"},
        "joints": [{"id": "K", "centers": ["G", "C"], "radii": ["b", "j"], "side": 1}],
        "foot": "K",
    },
    # the same four-bar plus one more dyad (a six-bar): X hangs from the crank tip and the coupler joint
    "sixbar-extra-dyad": {
        "params": {"a": 40.0, "l": 0.0, "m": 10.0, "b": 45.0, "j": 38.0, "p": 30.0, "q": 25.0},
        "crank": {"x": "a", "y": "l", "length": "m"},
        "joints": [
            {"id": "K", "centers": ["G", "C"], "radii": ["b", "j"], "side": 1},
            {"id": "X", "centers": ["C", "K"], "radii": ["p", "q"], "side": -1},
        ],
        "foot": "X",
    },
    # Jansen with a longer crank (a different gait) to catch code that only works for the textbook numbers
    "jansen-long-crank": {**J, "params": {**J["params"], "m": 16.0}},
}

THETAS = [2 * math.pi * k / 12 for k in range(12)]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in DESIGNS.items():
        ls = load_spec(spec)
        samples = []
        for th in THETAS:
            pose = solve_pose(ls, th)
            assert pose is not None, (name, th)
            samples.append({"theta": th, "points": {k: [round(v[0], 12), round(v[1], 12)] for k, v in pose.items()}})
        g = gait_metrics(ls, samples=180)
        doc = {
            "schema": "kinematics-contract/1",
            "name": name,
            "spec": spec,
            "tolerance": {"points": 1e-9, "gait": 1e-6},
            "gait": {"samples": 180, "width": g.width, "lift": g.lift, "stroke_length": g.stroke_length, "duty": g.duty},
            "samples": samples,
        }
        (OUT / f"{name}.json").write_text(json.dumps(doc, indent=1) + "\n")
        print(name, "duty", round(g.duty, 4), "lift", round(g.lift, 3))


if __name__ == "__main__":
    main()
