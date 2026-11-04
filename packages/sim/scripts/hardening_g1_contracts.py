"""Record energy-v2 fixtures separately, preserving and comparing old evidence.

Only run after analytic invariants pass. Existing files are never overwritten.
The intended change is left-endpoint timestamps/angles and discrete work, not
physics trajectories, force samples, geometry, audit thresholds or defaults.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

from strandbeest_sim import load_scenario, run

ROOT = Path(__file__).resolve().parents[3]


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    out = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(out)
    return out


def differences(old, new, prefix=""):
    if isinstance(old, dict) and isinstance(new, dict):
        out = {}
        for k in old.keys() | new.keys():
            out.update(differences(old.get(k), new.get(k), f"{prefix}.{k}".strip(".")))
        return out
    if old == new:
        return {}
    result = {"old": old, "new": new}
    if isinstance(old, list) and isinstance(new, list):
        a, b = np.asarray(old), np.asarray(new)
        result = {"old_shape": list(a.shape), "new_shape": list(b.shape)}
        if a.shape == b.shape and a.dtype.kind in "biuf" and b.dtype.kind in "biuf":
            result.update(max_abs_change=float(np.max(np.abs(a.astype(float) - b.astype(float)))),
                          changed_values=int(np.count_nonzero(a != b)), old_first=old[0], new_first=new[0])
    return {prefix: result}


def main():
    old_golden = ROOT / "contracts/sim-golden/runs.json"
    new_golden = ROOT / "contracts/sim-golden/runs-energy-v2.json"
    old_corpus = ROOT / "contracts/sim-run/cases.json"
    new_corpus = ROOT / "contracts/sim-run/cases-energy-v2.json"
    evidence = ROOT / "experiments/hardening-g1-energy-v2-contract-diff-2026-11-03.json"
    for p in (new_golden, new_corpus, evidence):
        if p.exists():
            raise FileExistsError(p)
    report = {"definition": "left-endpoint t_n observations; effective implicit force times average velocity; no trajectory changes",
              "old_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (old_golden, old_corpus)},
              "golden": {}, "corpus": {}}
    gold = json.loads(old_golden.read_text())
    sampler = module(ROOT / "contracts/sim-golden/generate.py").sample
    new_gold = copy.deepcopy(gold)
    for before, after in zip(gold["runs"], new_gold["runs"]):
        res = run(load_scenario(before["scenario"]))
        after["metrics"] = {k: None if v != v else v if isinstance(v, bool) else float(v) for k, v in res.metrics.items()}
        after["samples"] = {k: sampler(getattr(res, k)) for k in ("t", "psi", "x", "z", "torque")}
        assert len(res.t) == before["n"] and res.stalled == before["stalled"]
        for k in ("x", "z", "torque"):
            np.testing.assert_allclose(after["samples"][k], before["samples"][k], rtol=1e-7, atol=1e-12)
        if res.frames is not None:
            f = res.frames
            after["frames"] = {"count": len(f["t"]), "bodies": f["pos"].shape[1], "contact_sum": int(f["contact"].sum()),
                               "pos_sum": float(np.round(f["pos"].astype(np.float64).sum(), 4))}
            assert after["frames"] == before["frames"]
        report["golden"][before["name"]] = differences(before, after)
        print("golden", before["name"], flush=True)
    new_gold["_doc"] = report["definition"] + "; old runs.json retained; see hardening_g1_contracts.py and contract-diff experiment."
    corpus = json.loads(old_corpus.read_text())
    new_cases = copy.deepcopy(corpus)
    generator = module(ROOT / "contracts/generate_sim_run.py")
    for before, after in zip(corpus["cases"], new_cases["cases"]):
        after["expected"] = generator.one(after["overrides"])
        diff = differences(before["expected"], after["expected"])
        report["corpus"][before["name"]] = diff
        print("corpus", before["name"], sorted(diff), flush=True)
    # Exercise the previously omitted browser work channel with an explicit case.
    drag = {"drive": {"kind": "sail"}, "walker": {"body_drag_area": .01}, "wind": {"speed": 3.0},
            "run": {"revolutions": .1, "max_time": 3, "frame_rate": 0}}
    new_cases["cases"].append({"name": "sail-body-drag", "design": generator.DESIGN, "overrides": drag,
                                "expected": generator.one(drag)})
    new_cases["note"] = new_gold["_doc"]
    for path, data in ((new_golden, new_gold), (new_corpus, new_cases), (evidence, report)):
        with path.open("x") as f:
            json.dump(data, f, separators=(",", ":"), allow_nan=False)
            f.write("\n")


if __name__ == "__main__":
    main()
