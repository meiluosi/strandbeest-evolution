"""One design in, every stage out: validate -> evaluate -> simulate -> print pack. Shared by the CLI and the API."""

from __future__ import annotations

import argparse
import json
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
    doc = {
        "schema_version": 1,
        "id": rid,
        "design_name": design.name,
        "scenario": json.loads(sc.model_dump_json()),
        "metrics": {k: (None if v != v else v) for k, v in res.metrics.items()},
        "stalled": res.stalled,
        "arrays_file": "arrays.npz",
        "provenance": {"code_version": code_version(), "engine": "mujoco", "engine_version": mujoco.__version__,
                       "created": datetime.now(timezone.utc).isoformat()},
    }
    validate("run", doc)
    (out / "run.json").write_text(json.dumps(doc, indent=2))
    return doc


def full_pipeline(design: Design, out_dir: Path, overrides: dict[str, Any] | None = None, skip_sim: bool = False) -> dict[str, Any]:
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
    a = ap.parse_args(argv)
    rep = full_pipeline(Design.load(a.design), Path(a.out), skip_sim=a.skip_sim)
    print(json.dumps(rep, indent=2))
    raise SystemExit(1 if rep["fabrication"]["failed_checks"] else 0)


if __name__ == "__main__":
    main()
