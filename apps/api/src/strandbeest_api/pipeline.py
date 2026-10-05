"""One design in, every stage out: validate -> evaluate -> simulate -> print pack. Shared by the CLI and the API."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from strandbeest_common import Design, gait_metrics
from strandbeest_common.schemas import validate
from strandbeest_fab import export as fab_export
from strandbeest_sim import run as sim_run
from strandbeest_sim import scenario_from_design


def code_version() -> str:
    env = os.environ.get("STRANDBEEST_CODE_VERSION")
    if env and env != "unknown":
        return env
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).parent).stdout.strip()
    except Exception:
        return "unknown"


def evaluate(design: Design) -> dict[str, Any]:
    g = gait_metrics(design.spec)
    return {"gait": g.asdict(), "bar_mass_per_m_kg": design.bar_mass_per_m()}


def simulate(design: Design, out_dir: Path, overrides: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Run the simulator and write run.json (validated against the Run schema) plus arrays.npz."""
    rid = run_id or uuid.uuid4().hex[:12]
    out = Path(out_dir) / rid
    out.mkdir(parents=True, exist_ok=True)
    sc = scenario_from_design(design, overrides)
    res = sim_run(sc)
    np.savez(out / "arrays.npz", t=res.t, psi=res.psi, x=res.x, z=res.z, torque=res.torque)
    if res.frames is not None:
        np.savez_compressed(out / "frames.npz", **res.frames)
        (out / "scene.json").write_text(json.dumps(res.scene))
    doc = {
        "schema_version": 1,
        "id": rid,
        "design_name": design.name,
        "scenario": json.loads(sc.model_dump_json()),
        "metrics": {k: (None if v != v else v) for k, v in res.metrics.items()},
        "stalled": res.stalled,
        "arrays_file": "arrays.npz",
        **({"frames_file": "frames.npz", "scene_file": "scene.json"} if res.frames is not None else {}),
        "provenance": {"code_version": code_version(), "engine": "mujoco", "engine_version": mujoco.__version__,
                       "created": datetime.now(timezone.utc).isoformat()},
    }
    validate("run", doc)
    (out / "run.json").write_text(json.dumps(doc, indent=2))
    return doc


# Friction-regularisation variants (docs/EXPERIMENTS.md section 8): on flat ground the torque level is mostly slip
# dissipation and moved by up to a factor 1.9 across these numerical choices, so a run is reported as a range.
ENSEMBLE: list[tuple[str, dict[str, Any]]] = [
    ("pyramidal cone (default)", {}),
    ("elliptic cone", {"solver": {"cone": "elliptic"}}),
    ("friction impedance ratio 10", {"solver": {"impratio": 10}}),
    ("no-slip iterations 10", {"solver": {"noslip_iterations": 10}}),
]
RANGE_METRICS = ("stride_per_rev", "mean_speed", "mean_torque", "peak_torque", "torque_ptp")
LOOP_TOLERANCE_FRACTION = 0.01  # a run is discarded if its loops opened more than this fraction of the leg size


def loop_tolerance(design: Design) -> float:
    """Metres of loop-constraint opening beyond which a run is not trusted: 1 % of the mean hip-to-foot distance."""
    from strandbeest_common.gait import foot_path

    path = foot_path(design.spec) or [(0.0, 1.0)]
    size = sum((x * x + y * y) ** 0.5 for x, y in path) / len(path) * design.walker["unit_m"]
    return LOOP_TOLERANCE_FRACTION * size


def _merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict):
            _merge(dst.setdefault(k, {}), v)
        else:
            dst[k] = v
    return dst


def _variant(design: Design, overrides: dict[str, Any] | None, extra: dict[str, Any]) -> dict[str, Any]:
    ov = _merge(json.loads(json.dumps(overrides or {})), extra)
    ov.setdefault("run", {})["frame_rate"] = 0  # variants are not replayed
    res = sim_run(scenario_from_design(design, ov))
    m = {k: (None if isinstance(v, float) and v != v else v) for k, v in res.metrics.items()}
    ok = (
        not res.stalled
        and all(isinstance(m.get(k), (int, float)) for k in RANGE_METRICS)
        and m.get("max_loop_violation", 1.0) < loop_tolerance(design)
    )
    reason = "" if ok else ("stalled" if res.stalled else "loops opened or non-finite metrics")
    return {"metrics": m, "valid": ok, "reason": reason}


def simulate_ensemble(design: Design, out_dir: Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Base run (with arrays) plus the friction-regularisation variants, and the range of each metric over valid runs."""
    from concurrent.futures import ThreadPoolExecutor

    base = simulate(design, out_dir, overrides)
    others = ENSEMBLE[1:]
    with ThreadPoolExecutor(max_workers=len(others)) as ex:  # MuJoCo releases the GIL while stepping
        results = list(ex.map(lambda nv: _variant(design, overrides, nv[1]), others))
    variants = [{"name": ENSEMBLE[0][0], "overrides": {}, "valid": base["metrics"].get("max_loop_violation", 1.0) < loop_tolerance(design) and not base["stalled"],
                 "metrics": base["metrics"]}]
    for (name, ov), r in zip(others, results):
        row = {"name": name, "overrides": ov, "valid": r["valid"], "metrics": r["metrics"]}
        if r["reason"]:
            row["reason"] = r["reason"]
        variants.append(row)
    ranges = {}
    for k in RANGE_METRICS:
        vals = [v["metrics"][k] for v in variants if v["valid"] and isinstance(v["metrics"].get(k), (int, float))]
        if vals:
            ranges[k] = [min(vals), max(vals)]
    base["ensemble"] = {
        "variants": variants,
        "ranges": ranges,
        "note": "Torque level depends on how stick-slip friction is regularised; the range spans four numerical settings, not measurement uncertainty.",
    }
    validate("run", base)
    (Path(out_dir) / base["id"] / "run.json").write_text(json.dumps(base, indent=2))
    return base


def full_pipeline(design: Design, out_dir: Path, overrides: dict[str, Any] | None = None, skip_sim: bool = False, ensemble: bool = True) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"design": design.name, "evaluation": evaluate(design)}
    manifest = fab_export(design, out / "print")
    report["fabrication"] = {
        "parts": len(manifest["parts"]),
        "layers_per_leg": manifest["layers_per_leg"],
        "failed_checks": [c["name"] for c in manifest["checks"] if c["status"] == "fail"],
        "warnings": [c["name"] for c in manifest["checks"] if c["status"] == "warn"],
    }
    if not skip_sim:
        run = simulate(design, out / "runs", overrides)
        report["simulation"] = {"run_id": run["id"], "metrics": run["metrics"], "stalled": run["stalled"]}
    (out / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="strandbeest-pipeline", description="validate, evaluate, simulate and export a Design")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("design")
    r.add_argument("out")
    r.add_argument("--skip-sim", action="store_true", help="skip the (slow) simulation")
    r.add_argument("--no-ensemble", action="store_true", help="single run instead of the friction-regularisation range")
    a = ap.parse_args(argv)
    rep = full_pipeline(Design.load(a.design), Path(a.out), skip_sim=a.skip_sim, ensemble=not a.no_ensemble)
    print(json.dumps(rep, indent=2))
    raise SystemExit(1 if rep["fabrication"]["failed_checks"] else 0)


if __name__ == "__main__":
    main()
