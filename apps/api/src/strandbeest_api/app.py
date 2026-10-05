"""FastAPI orchestration layer. No physics here: it validates, queues, stores and serves."""

from __future__ import annotations

import json
import os
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
from strandbeest_rig import Calibration, convert_raw

from .jobs import JobContext, JobStore, Workers
from .pipeline import evaluate, simulate, simulate_ensemble
from .sweeps import expand, run_sweep

PARAMS = {"contact_stiffness": CONTACT_STIFFNESS, "friction": FRICTION}


def create_app(data_dir: str | Path | None = None, workers: int | None = None) -> FastAPI:
    root = Path(data_dir or os.environ.get("STRANDBEEST_DATA", "data"))
    for sub in ("designs", "runs", "exports", "measurements", "profiles"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    n_workers = workers if workers is not None else int(os.environ.get("STRANDBEEST_WORKERS", "2"))
    origins = os.environ.get("STRANDBEEST_CORS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080").split(",")

    store = JobStore(root / "strandbeest.db")
    interrupted = store.recover()
    _reindex(store, root)

    def parse(doc: dict) -> Design:
        try:
            return Design(doc)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    def measurement_doc(m: Any) -> dict:
        if isinstance(m, str):
            p = root / "measurements" / f"{Path(m).name}.json"
            if not p.exists():
                raise HTTPException(404, "no such measurement")
            return json.loads(p.read_text())
        return m

    # -- job handlers (run inside worker threads) --------------------------
    def h_run(ctx: JobContext, payload: dict[str, Any]):
        d = Design(payload["design"])
        fn = simulate_ensemble if payload.get("ensemble", True) else simulate
        ctx.progress(0, 1, "simulating")
        doc = fn(d, root / "runs", payload.get("overrides"))
        store.index_run(doc)
        ctx.progress(1, 1, "done")
        return doc

    def h_calibration(ctx: JobContext, payload: dict[str, Any]):
        d = Design(payload["design"])
        profile = calibrate(d, measurement_doc(payload["measurement"]), [PARAMS[n] for n in payload["params"]], max_evals=payload["max_evals"])
        validate("profile", profile)
        (root / "profiles" / f"{profile['name']}.json").write_text(json.dumps(profile, indent=2))
        return profile

    def h_sweep(ctx: JobContext, payload: dict[str, Any]):
        return run_sweep(ctx, payload, root / "runs", parallel=max(1, n_workers + 1))

    pool = Workers(store, {"run": h_run, "calibration": h_calibration, "sweep": h_sweep}, n=n_workers)
    pool.start()

    app = FastAPI(title="Strandbeest platform API", version="0.2.0")
    app.state.store, app.state.workers = store, pool
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health():
        return {"ok": True, "interrupted_jobs_recovered": interrupted, "workers": n_workers}

    # -- designs -------------------------------------------------------------
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

    # -- jobs ----------------------------------------------------------------
    @app.post("/runs")
    def start_run(body: dict = Body(...)):
        d = parse(body["design"])
        return {"job_id": store.create("run", {"design": d.doc, "overrides": body.get("overrides"), "ensemble": body.get("ensemble", True)})}

    @app.post("/sweeps")
    def start_sweep(body: dict = Body(...)):
        d = parse(body["design"])
        try:
            points = expand(body["axes"])
        except (ValueError, KeyError) as e:
            raise HTTPException(422, str(e)) from e
        jid = store.create("sweep", {"design": d.doc, "axes": body["axes"], "overrides": body.get("overrides")})
        return {"job_id": jid, "points": len(points)}

    @app.post("/calibrations")
    def start_calibration(body: dict = Body(...)):
        d = parse(body["design"])
        names = body.get("params", ["contact_stiffness"])
        unknown = [n for n in names if n not in PARAMS]
        if unknown:
            raise HTTPException(422, f"unknown parameters {unknown}; available: {sorted(PARAMS)}")
        measurement_doc(body["measurement"])  # 404 early if it does not exist
        return {"job_id": store.create("calibration", {"design": d.doc, "measurement": body["measurement"], "params": names,
                                                        "max_evals": min(int(body.get("max_evals", 20)), 40)})}

    @app.get("/jobs")
    def list_jobs(status: str | None = None, kind: str | None = None, limit: int = 50):
        return store.list(status, kind, limit)

    @app.get("/jobs/{jid}")
    def get_job(jid: str):
        j = store.get(jid)
        if j is None:
            raise HTTPException(404, "no such job")
        return j

    @app.post("/jobs/{jid}/cancel")
    def cancel_job(jid: str):
        if store.get(jid) is None:
            raise HTTPException(404, "no such job")
        return {"cancel_requested": store.request_cancel(jid)}

    # -- runs ----------------------------------------------------------------
    @app.get("/runs")
    def list_runs(limit: int = 30):
        return store.list_runs(limit)

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
        step = max(1, len(a["t"]) // max_points)
        return {k: a[k][::step].tolist() for k in a.files}

    @app.get("/runs/{rid}/replay")
    def run_replay(rid: str, max_frames: int = 240):
        """Everything a viewer needs to replay a run: scene geometry, per-frame body poses, foot contacts and the time series."""
        folder = root / "runs" / Path(rid).name
        if not (folder / "frames.npz").exists():
            raise HTTPException(404, "this run has no recorded frames (sweep points and ensemble variants are not recorded)")
        fr = np.load(folder / "frames.npz")
        ar = np.load(folder / "arrays.npz")
        run_doc = json.loads((folder / "run.json").read_text())
        step = max(1, len(fr["t"]) // max_frames)
        sstep = max(1, len(ar["t"]) // 500)
        sc = run_doc["scenario"]
        # distance one crank revolution would carry the body if no foot slipped or was blocked: stance travel / duty factor
        from strandbeest_common import gait_metrics, load_spec

        g = gait_metrics(load_spec(sc["linkage"]["spec"])) if isinstance(sc["linkage"]["spec"], dict) else None
        nominal = (g.stroke_length / g.duty * sc["walker"]["unit"]) if g and g.duty > 0 else None
        return {
            "scene": json.loads((folder / "scene.json").read_text()),
            "t": np.round(fr["t"][::step], 4).tolist(),
            "pos": np.round(fr["pos"][::step], 4).tolist(),
            "quat": np.round(fr["quat"][::step], 4).tolist(),
            "contact": fr["contact"][::step].astype(int).tolist(),
            "series": {k: np.round(ar[k][::sstep], 5).tolist() for k in ("t", "psi", "x", "torque")},
            "metrics": run_doc["metrics"],
            "stalled": run_doc.get("stalled", False),
            "nominal_stride_m": nominal,
            "revolutions": float(ar["psi"][-1] / (2 * np.pi)),
            "info": {"terrain": sc["terrain"], "drive": sc["drive"]["kind"], "wind": sc["wind"], "environment": sc["environment"]},
        }

    # -- exports -------------------------------------------------------------
    @app.post("/exports")
    def make_export(doc: dict = Body(...)):
        d = parse(doc)
        import uuid

        eid = uuid.uuid4().hex[:12]
        manifest = fab_export(d, root / "exports" / eid)
        return {"export_id": eid, "parts": len(manifest["parts"]), "layers_per_leg": manifest["layers_per_leg"],
                "checks": manifest["checks"], "download": f"/exports/{eid}/download"}

    @app.get("/exports/{eid}/parts")
    def export_parts(eid: str):
        p = root / "exports" / Path(eid).name / "parts.json"
        if not p.exists():
            raise HTTPException(404, "no such export")
        return json.loads(p.read_text())

    @app.get("/exports/{eid}/stl/{name}")
    def export_stl(eid: str, name: str):
        p = root / "exports" / Path(eid).name / "stl" / f"{Path(name).name}.stl"
        if not p.exists():
            raise HTTPException(404, "no such part")
        return FileResponse(p, media_type="model/stl")

    @app.get("/exports/{eid}/download")
    def download(eid: str):
        zips = list((root / "exports" / Path(eid).name).glob("*.zip"))
        if not zips:
            raise HTTPException(404, "no such export")
        return FileResponse(zips[0], filename=zips[0].name, media_type="application/zip")

    # -- measurements --------------------------------------------------------
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
        return measurement_doc(mid)

    @app.get("/rig/calibration-template")
    def calibration_template():
        return Calibration().asdict()

    @app.post("/rig/convert")
    def rig_convert(body: dict = Body(...)):
        """Raw rig CSV + calibration -> Measurement document with a quality report. Nothing is saved; POST the result to /measurements."""
        import io

        try:
            track = None
            if body.get("track_csv"):
                a = np.genfromtxt(io.StringIO(body["track_csv"]), delimiter=",", names=True)
                track = (np.asarray(a["t_s"], float), np.asarray(a["x_m"], float))
            return convert_raw(
                body["raw_csv"], Calibration.load(body.get("calibration") or {}), id=body["id"], design_name=body["design_name"],
                kind=body.get("kind", "motor_no_wind"), omega_rad_s=body.get("omega"), wind_m_s=body.get("wind"),
                surface=body.get("surface", ""), build_note=body.get("build_note", ""), raw_name=body.get("raw_name", ""),
                track=track, track_offset_s=body.get("track_offset_s"),
            )
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f"{type(e).__name__}: {e}") from e

    @app.post("/compare")
    def compare(body: dict = Body(...)):
        """Measured vs simulated crank torque per crank-angle bin, plus a single mismatch number."""
        if "measurement" not in body:
            raise HTTPException(422, "measurement required")
        meas = measurement_doc(body["measurement"])
        try:
            validate("measurement", meas)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        ch = meas["channels"]
        if "psi" not in ch or "torque" not in ch:
            raise HTTPException(422, "measurement needs psi and torque channels to compare")
        mc = curves(np.array(ch["t"]), np.array(ch["psi"]), np.array(ch["torque"]), np.array(ch["x"]) if "x" in ch else None, 0.5)
        p = root / "runs" / Path(body["run_id"]).name / "arrays.npz"
        if not p.exists():
            raise HTTPException(404, "no such run")
        a = np.load(p)
        sc = curves(a["t"], a["psi"], a["torque"], a["x"], skip_rev=0.5)
        nb = len(mc.torque)
        clean = lambda arr: [None if v != v else float(v) for v in arr]  # noqa: E731
        d = distance(mc, sc)
        return {"angle_deg": [(i + 0.5) / nb * 360.0 for i in range(nb)], "measured": clean(mc.torque), "simulated": clean(sc.torque),
                "stride_measured": mc.stride, "stride_simulated": sc.stride, "distance": None if d != d or d == float("inf") else d}

    return app


def _reindex(store: JobStore, root: Path) -> None:
    """Rebuild the run index from run.json files (covers runs written before the index existed)."""
    for p in (root / "runs").glob("*/run.json"):
        d = json.loads(p.read_text())
        if not store.has_run(d["id"]):
            store.index_run(d)


def serve() -> None:
    import uvicorn

    uvicorn.run(create_app(), host=os.environ.get("STRANDBEEST_HOST", "127.0.0.1"), port=int(os.environ.get("STRANDBEEST_PORT", "8000")))
