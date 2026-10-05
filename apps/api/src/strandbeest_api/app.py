"""FastAPI orchestration layer. No physics here: it validates, queues, stores and serves."""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from strandbeest_calib import CONTACT_STIFFNESS, FRICTION, calibrate
from strandbeest_calib.compare import curves, distance
from strandbeest_common import Design
from strandbeest_common.schemas import validate
from strandbeest_fab import export as fab_export

from .pipeline import evaluate, simulate, simulate_ensemble


def create_app(data_dir: str | Path | None = None, workers: int = 2) -> FastAPI:
    root = Path(data_dir or os.environ.get("STRANDBEEST_DATA", "data"))
    for sub in ("designs", "runs", "exports", "measurements", "profiles"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Strandbeest platform API", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
    pool = ThreadPoolExecutor(max_workers=workers)
    jobs: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()

    def parse(doc: dict) -> Design:
        try:
            return Design(doc)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/designs/validate")
    def validate_design(doc: dict = Body(...)):
        try:
            Design(doc)
            return {"ok": True, "errors": []}
        except ValueError as e:
            return {"ok": False, "errors": str(e).splitlines()[1:]}

    @app.post("/designs")
    def save_design(doc: dict = Body(...)):
        d = parse(doc)
        (root / "designs" / f"{d.name}.json").write_text(json.dumps(d.doc, indent=2))
        return {"name": d.name}

    @app.get("/designs")
    def list_designs():
        return sorted(p.stem for p in (root / "designs").glob("*.json"))

    @app.get("/designs/{name}")
    def get_design(name: str):
        p = root / "designs" / f"{Path(name).name}.json"
        if not p.exists():
            raise HTTPException(404, "no such design")
        return json.loads(p.read_text())

    @app.post("/evaluate")
    def evaluate_design(doc: dict = Body(...)):
        return evaluate(parse(doc))

    def submit(fn, *args) -> str:
        jid = uuid.uuid4().hex[:12]
        with lock:
            jobs[jid] = {"status": "queued", "result": None, "error": None}

        def work():
            with lock:
                jobs[jid]["status"] = "running"
            try:
                res = fn(*args)
                with lock:
                    jobs[jid].update(status="done", result=res)
            except Exception as e:  # report to the client instead of losing it in the pool
                with lock:
                    jobs[jid].update(status="failed", error=f"{type(e).__name__}: {e}")

        pool.submit(work)
        return jid

    @app.post("/runs")
    def start_run(body: dict = Body(...)):
        d = parse(body["design"])
        overrides = body.get("overrides")
        fn = simulate_ensemble if body.get("ensemble", True) else simulate
        jid = submit(lambda: fn(d, root / "runs", overrides))
        return {"job_id": jid}

    @app.get("/jobs/{jid}")
    def job(jid: str):
        if jid not in jobs:
            raise HTTPException(404, "no such job")
        return jobs[jid]

    @app.get("/runs")
    def list_runs(limit: int = 30):
        rows = []
        for p in (root / "runs").glob("*/run.json"):
            d = json.loads(p.read_text())
            rows.append({"id": d["id"], "design_name": d["design_name"], "created": d["provenance"].get("created", ""),
                         "stalled": d.get("stalled", False), "metrics": d["metrics"],
                         "ranges": d.get("ensemble", {}).get("ranges")})
        rows.sort(key=lambda r: r["created"], reverse=True)
        return rows[:limit]

    @app.get("/runs/{rid}")
    def get_run(rid: str):
        p = root / "runs" / Path(rid).name / "run.json"
        if not p.exists():
            raise HTTPException(404, "no such run")
        return json.loads(p.read_text())

    @app.get("/runs/{rid}/series")
    def run_series(rid: str, max_points: int = 600):
        p = root / "runs" / Path(rid).name / "arrays.npz"
        if not p.exists():
            raise HTTPException(404, "no such run")
        a = np.load(p)
        n = len(a["t"])
        step = max(1, n // max_points)
        return {k: a[k][::step].tolist() for k in a.files}

    @app.post("/exports")
    def make_export(doc: dict = Body(...)):
        d = parse(doc)
        eid = uuid.uuid4().hex[:12]
        out = root / "exports" / eid
        manifest = fab_export(d, out)
        return {
            "export_id": eid,
            "parts": len(manifest["parts"]),
            "layers_per_leg": manifest["layers_per_leg"],
            "checks": manifest["checks"],
            "download": f"/exports/{eid}/download",
        }

    @app.get("/exports/{eid}/parts")
    def export_parts(eid: str):
        p = root / "exports" / Path(eid).name / "parts.json"
        if not p.exists():
            raise HTTPException(404, "no such export")
        return json.loads(p.read_text())

    @app.post("/measurements")
    def save_measurement(doc: dict = Body(...)):
        try:
            validate("measurement", doc)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        (root / "measurements" / f"{Path(doc['id']).name}.json").write_text(json.dumps(doc))
        return {"id": doc["id"]}

    @app.get("/measurements")
    def list_measurements():
        out = []
        for p in sorted((root / "measurements").glob("*.json")):
            d = json.loads(p.read_text())
            out.append({"id": d["id"], "design_name": d["design_name"], "synthetic": d["synthetic"], "conditions": d["conditions"]})
        return out

    @app.get("/measurements/{mid}")
    def get_measurement(mid: str):
        p = root / "measurements" / f"{Path(mid).name}.json"
        if not p.exists():
            raise HTTPException(404, "no such measurement")
        return json.loads(p.read_text())

    def _run_curves(rid: str):
        p = root / "runs" / Path(rid).name / "arrays.npz"
        if not p.exists():
            raise HTTPException(404, "no such run")
        a = np.load(p)
        return curves(a["t"], a["psi"], a["torque"], a["x"], skip_rev=0.5)

    @app.post("/compare")
    def compare(body: dict = Body(...)):
        """Measured vs simulated crank torque per crank-angle bin, plus a single mismatch number."""
        meas = body["measurement"] if "measurement" in body else None
        if meas is None:
            raise HTTPException(422, "measurement required")
        if isinstance(meas, str):
            meas = get_measurement(meas)
        try:
            validate("measurement", meas)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        ch = meas["channels"]
        if "psi" not in ch or "torque" not in ch:
            raise HTTPException(422, "measurement needs psi and torque channels to compare")
        mc = curves(np.array(ch["t"]), np.array(ch["psi"]), np.array(ch["torque"]), np.array(ch["x"]) if "x" in ch else None, 0.5)
        sc = _run_curves(body["run_id"])
        nb = len(mc.torque)
        centers = [(i + 0.5) / nb * 360.0 for i in range(nb)]
        clean = lambda arr: [None if v != v else float(v) for v in arr]  # noqa: E731
        d = distance(mc, sc)
        return {"angle_deg": centers, "measured": clean(mc.torque), "simulated": clean(sc.torque),
                "stride_measured": mc.stride, "stride_simulated": sc.stride, "distance": None if d != d or d == float("inf") else d}

    PARAMS = {"contact_stiffness": CONTACT_STIFFNESS, "friction": FRICTION}

    @app.post("/calibrations")
    def start_calibration(body: dict = Body(...)):
        d = parse(body["design"])
        names = body.get("params", ["contact_stiffness"])
        unknown = [n for n in names if n not in PARAMS]
        if unknown:
            raise HTTPException(422, f"unknown parameters {unknown}; available: {sorted(PARAMS)}")
        meas = body["measurement"]
        if isinstance(meas, str):
            meas = get_measurement(meas)
        evals = min(int(body.get("max_evals", 20)), 40)

        def work():
            profile = calibrate(d, meas, [PARAMS[n] for n in names], max_evals=evals)
            validate("profile", profile)
            (root / "profiles" / f"{profile['name']}.json").write_text(json.dumps(profile, indent=2))
            return profile

        return {"job_id": submit(work)}

    @app.get("/exports/{eid}/download")
    def download(eid: str):
        folder = root / "exports" / Path(eid).name
        zips = list(folder.glob("*.zip"))
        if not zips:
            raise HTTPException(404, "no such export")
        return FileResponse(zips[0], filename=zips[0].name, media_type="application/zip")

    return app


def serve() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
