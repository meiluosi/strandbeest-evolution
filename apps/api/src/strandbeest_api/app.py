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

from strandbeest_common import Design
from strandbeest_fab import export as fab_export

from .pipeline import evaluate, simulate, simulate_ensemble


def create_app(data_dir: str | Path | None = None, workers: int = 2) -> FastAPI:
    root = Path(data_dir or os.environ.get("STRANDBEEST_DATA", "data"))
    for sub in ("designs", "runs", "exports"):
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
