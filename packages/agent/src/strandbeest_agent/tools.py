"""The hand-written tools (reading designs, simulating, the glass-box layers, the lab, notes) and the default registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from strandbeest_common import Design
from strandbeest_common.guard import default_problems
from strandbeest_common.ids import new_ulid
from strandbeest_common.migrate import migrate_any
from strandbeest_common.ops import OPS
from strandbeest_fab import export as fab_export
from strandbeest_fab import printable_problems

from .registry import Registry, Session, Tool, operation_tools
from .workspace import ToolError, Workspace

REF = {"type": "string", "description": "Design id or name"}
RUN = {"type": "string", "description": "Run id"}


def obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": required or []}


# ---- designs ------------------------------------------------------------------------------------------------------
def design_list(ws: Workspace, s: Session, a: dict) -> Any:
    out = []
    for did in ws.design_ids():
        d = json.loads(ws._doc_path(did).read_text())
        out.append({"id": did, "name": d["name"], "legs": d["walker"]["legs"], "joints": len(d["linkage"]["joints"])})
    return out


def design_get(ws: Workspace, s: Session, a: dict) -> Any:
    return ws.history(a["design"]).design


def design_create(ws: Workspace, s: Session, a: dict) -> Any:
    did = ws.create(doc=a.get("document"), example=a.get("example"), name=a.get("name"))
    return {"design_id": did, "design": ws.history(did).design}


def design_history(ws: Workspace, s: Session, a: dict) -> Any:
    h = ws.history(a["design"])
    return {"steps": h.steps, "can_undo": h.can_undo, "can_redo": h.can_redo}


def design_guard(ws: Workspace, s: Session, a: dict) -> Any:
    d = ws.history(a["design"]).design
    problems = default_problems(d) + printable_problems(d)
    return {"ok": not any(p["level"] == "error" for p in problems), "problems": problems}


def design_undo(ws: Workspace, s: Session, a: dict) -> Any:
    from strandbeest_common.ops import OpError

    try:
        return {"undone": ws.undo(a["design"])["undone"]}
    except OpError as e:
        raise ToolError(e.code, e.message) from e


def design_redo(ws: Workspace, s: Session, a: dict) -> Any:
    from strandbeest_common.ops import OpError

    try:
        return {"redone": ws.redo(a["design"])["redone"]}
    except OpError as e:
        raise ToolError(e.code, e.message) from e


def design_describe_ops(ws: Workspace, s: Session, a: dict) -> Any:
    return [{"type": k, "doc": v.doc} for k, v in sorted(OPS.items())]


# ---- simulate -----------------------------------------------------------------------------------------------------
BRIEF = ("stride_per_rev", "mean_speed", "mean_torque", "peak_torque", "max_loop_violation", "max_penetration", "energy_in_per_rev",
         "energy_contact_share", "energy_residual_share", "steady_window")


def _brief(doc: dict) -> dict:
    m = doc["metrics"]
    return {
        "run_id": doc["id"],
        "design_id": doc["design_id"],
        "stalled": doc.get("stalled", False),
        "metrics": {k: m.get(k) for k in BRIEF if k in m},
        "diagnosis": [{"code": d["code"], "severity": d["severity"], "message": d["message"]} for d in doc.get("diagnosis", [])[:3]],
        "events": _count([e["kind"] for e in doc.get("events", [])]),
    }


def _count(items: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def simulate_run(ws: Workspace, s: Session, a: dict) -> Any:
    from strandbeest_api.pipeline import simulate
    from strandbeest_sim.scenes import scene_overrides

    d = Design(ws.history(a["design"]).design)
    overrides = scene_overrides(a.get("scene", "flat"), wind_speed=float(a.get("wind_speed", 3.0)), revolutions=float(a.get("revolutions", 2.0)))
    for k, v in (a.get("overrides") or {}).items():
        overrides.setdefault(k, {}).update(v) if isinstance(v, dict) else overrides.__setitem__(k, v)
    try:
        doc = simulate(d, ws.root / "runs", overrides)
    except (ValueError, KeyError) as e:
        raise ToolError("simulation_failed", str(e)) from e
    return _brief(doc)


def _run_doc(ws: Workspace, rid: str) -> dict:
    return json.loads((ws.run_dir(rid) / "run.json").read_text())


def simulate_list_runs(ws: Workspace, s: Session, a: dict) -> Any:
    out = []
    for rid in ws.run_ids():
        d = _run_doc(ws, rid)
        out.append({"run_id": rid, "design_id": d["design_id"], "created": d["provenance"].get("created"), "stalled": d.get("stalled", False),
                    "stride_per_rev": d["metrics"].get("stride_per_rev")})
    return out


def simulate_get_run(ws: Workspace, s: Session, a: dict) -> Any:
    return _brief(_run_doc(ws, a["run"]))


LAYERS = ("summary", "diagnosis", "events", "energy", "feet", "series")


def _decimate(arr: np.ndarray, n: int) -> list:
    step = max(1, len(arr) // n)
    return np.round(arr[::step], 6).tolist()


def simulate_query(ws: Workspace, s: Session, a: dict) -> Any:
    """Read one layer of a finished run: the glass-box data an agent needs to explain a result."""
    layer = a.get("layer", "summary")
    if layer not in LAYERS:
        raise ToolError("bad_args", f"unknown layer '{layer}'; available: {list(LAYERS)}")
    doc = _run_doc(ws, a["run"])
    if layer == "summary":
        return {**_brief(doc), "scenario": doc["scenario"]}
    if layer == "diagnosis":
        return doc.get("diagnosis", [])
    if layer == "events":
        kinds = set(a.get("kinds") or [])
        ev = [e for e in doc.get("events", []) if not kinds or e["kind"] in kinds]
        limit = int(a.get("limit", 100))
        return {"count": len(ev), "events": ev[:limit]}
    arrays = np.load(ws.run_dir(a["run"]) / "arrays.npz")
    n = int(a.get("max_points", 200))
    if layer == "energy":
        m = doc["metrics"]
        return {"metrics": {k: v for k, v in m.items() if k.startswith("energy")},
                "series": {k: _decimate(arrays[k], n) for k in ("t", "e_in", "e_contact", "e_loops", "e_friction", "kinetic", "potential") if k in arrays.files}}
    if layer == "feet":
        if "foot_normal" not in arrays.files:
            raise ToolError("not_recorded", "this run has no foot loads (made before they were recorded)")
        normal, slip = arrays["foot_normal"], arrays["foot_slip"]
        return [{"foot": k, "stance_fraction": float((normal[:, k] > 1e-6).mean()), "mean_normal_n_when_down": float(normal[:, k][normal[:, k] > 1e-6].mean()) if (normal[:, k] > 1e-6).any() else 0.0,
                 "peak_normal_n": float(normal[:, k].max()), "slip_fraction_of_stance": float(((slip[:, k] > 0.02) & (normal[:, k] > 1e-6)).sum() / max(1, (normal[:, k] > 1e-6).sum()))}
                for k in range(normal.shape[1])]
    names = a.get("names") or ["t", "psi", "x", "torque"]
    missing = [k for k in names if k not in arrays.files]
    if missing:
        raise ToolError("bad_args", f"no series {missing}; available: {sorted(arrays.files)}")
    return {k: _decimate(arrays[k], n) for k in names}


def simulate_audit(ws: Workspace, s: Session, a: dict) -> Any:
    """The simulator skeptic on a stored run: do its numbers satisfy the invariants a trustworthy run must satisfy?"""
    from strandbeest_sim import sim_config
    from strandbeest_sim.skeptic import audit

    doc = _run_doc(ws, a["run"])
    arrays = np.load(ws.run_dir(a["run"]) / "arrays.npz")
    findings = audit(sim_config(doc["scenario"]), doc["metrics"], {k: arrays[k] for k in arrays.files}, doc.get("stalled", False))
    return {"trustworthy": not findings, "findings": [{"check": f.check, "message": f.message, "evidence": f.evidence} for f in findings],
            "checked": ["energy_closure", "loop_closure", "penetration", "stride_vs_kinematics", "support"]}


# ---- lab ----------------------------------------------------------------------------------------------------------
def _measurements(ws: Workspace) -> list[dict]:
    d = ws.root / "measurements"
    return [migrate_any(json.loads(p.read_text()), "measurement") for p in sorted(d.glob("*.json"))] if d.exists() else []


def lab_list(ws: Workspace, s: Session, a: dict) -> Any:
    return [{"id": m["id"], "name": m["name"], "design_id": m["design_id"], "synthetic": m["synthetic"], "conditions": m["conditions"]} for m in _measurements(ws)]


def lab_compare(ws: Workspace, s: Session, a: dict) -> Any:
    from strandbeest_calib.compare import curves, distance

    meas = next((m for m in _measurements(ws) if a["measurement"] in (m["id"], m["name"])), None)
    if meas is None:
        raise ToolError("unknown_measurement", f"no measurement '{a['measurement']}'")
    ch = meas["channels"]
    if "psi" not in ch or "torque" not in ch:
        raise ToolError("bad_measurement", "needs psi and torque channels")
    mc = curves(np.array(ch["t"]), np.array(ch["psi"]), np.array(ch["torque"]), np.array(ch["x"]) if "x" in ch else None, 0.5)
    arr = np.load(ws.run_dir(a["run"]) / "arrays.npz")
    sc = curves(arr["t"], arr["psi"], arr["torque"], arr["x"], skip_rev=0.5)
    dist = distance(mc, sc)
    return {"mismatch": None if dist != dist or dist == float("inf") else float(dist), "stride_measured": mc.stride, "stride_simulated": sc.stride,
            "note": "synthetic measurement: only shows the pipeline works" if meas["synthetic"] else "measured data"}


# ---- notes --------------------------------------------------------------------------------------------------------
def notes_add(ws: Workspace, s: Session, a: dict) -> Any:
    note = {"id": new_ulid(), "actor": s.actor, "text": a["text"], "design": a.get("design"), "run": a.get("run"), "tags": a.get("tags", [])}
    ws.add_note(note)
    return {"note_id": note["id"]}


def notes_list(ws: Workspace, s: Session, a: dict) -> Any:
    notes = ws.notes()
    if a.get("design"):
        did = ws.resolve(a["design"])
        notes = [n for n in notes if n.get("design") in (a["design"], did)]
    return notes


# ---- fab (confirm) ------------------------------------------------------------------------------------------------
def fab_export_tool(ws: Workspace, s: Session, a: dict) -> Any:
    d = Design(ws.history(a["design"]).design)
    out = ws.root / "exports" / new_ulid()
    manifest = fab_export(d, out)
    return {"export_dir": str(out), "parts": len(manifest["parts"]), "checks": manifest["checks"]}


def default_registry() -> Registry:
    t = Tool
    hand = [
        t("design.list", "List the designs in the workspace.", obj({}), "read", design_list),
        t("design.get", "The current design document (schema v2).", obj({"design": REF}, ["design"]), "read", design_get),
        t("design.create", "Create a new design from a bundled example or a design document. It becomes a new asset with a new id; the source is recorded as its parent.",
          obj({"example": {"type": "string", "description": "Example name, e.g. jansen-small-6leg"}, "document": {"type": "object", "description": "A full design document"}, "name": {"type": "string"}}), "write", design_create),
        t("design.history", "The operation log of a design in undo steps (who changed what and why).", obj({"design": REF}, ["design"]), "read", design_history),
        t("design.guard", "Every validity problem of the design: schema, kinematics (assembly, branch flip) and printability.", obj({"design": REF}, ["design"]), "read", design_guard),
        t("design.undo", "Undo the last step of the design's log.", obj({"design": REF}, ["design"]), "write", design_undo),
        t("design.redo", "Redo the last undone step.", obj({"design": REF}, ["design"]), "write", design_redo),
        t("design.describe_ops", "The edit operations that exist, with one-line documentation.", obj({}), "read", design_describe_ops),
        t("simulate.run", "Simulate a design in a scene (flat, slope, step, bumps, wind, gusts, mars, titan, venus, moon) with MuJoCo. Costs one run of the session budget. Returns the headline numbers and the top diagnosis; read more with simulate.query.",
          obj({"design": REF, "scene": {"type": "string", "default": "flat"}, "revolutions": {"type": "number", "exclusiveMinimum": 0, "maximum": 6, "default": 2},
               "wind_speed": {"type": "number", "minimum": 0, "description": "m/s, for the sail scenes"}, "overrides": {"type": "object", "description": "Extra scenario overrides in the flat shape (terrain, wind, drive, environment, solver, run)"}}, ["design"]),
          "budget", simulate_run),
        t("simulate.list_runs", "Runs in the workspace.", obj({}), "read", simulate_list_runs),
        t("simulate.get_run", "Headline numbers, diagnosis and event counts of a run.", obj({"run": RUN}, ["run"]), "read", simulate_get_run),
        t("simulate.query", "Read one layer of a run: summary, diagnosis, events (filter by kinds), energy (account and series), feet (stance, load, slip per foot), series.",
          obj({"run": RUN, "layer": {"enum": list(LAYERS), "default": "summary"}, "kinds": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer", "minimum": 1},
               "names": {"type": "array", "items": {"type": "string"}}, "max_points": {"type": "integer", "minimum": 10, "maximum": 1000}}, ["run"]), "read", simulate_query),
        t("simulate.audit", "Run the simulator skeptic on a run: energy closure, loop closure, penetration, stride against the kinematic stride, support. Say whether to trust the numbers.", obj({"run": RUN}, ["run"]), "read", simulate_audit),
        t("lab.list_measurements", "Measurements in the workspace (data from a real build).", obj({}), "read", lab_list),
        t("lab.compare", "Compare a measurement with a simulation run: crank torque against crank angle, one mismatch number.", obj({"measurement": {"type": "string"}, "run": RUN}, ["measurement", "run"]), "read", lab_compare),
        t("notes.add", "Write a lab note, optionally tied to a design or run.", obj({"text": {"type": "string", "minLength": 1}, "design": REF, "run": RUN, "tags": {"type": "array", "items": {"type": "string"}}}, ["text"]), "write", notes_add),
        t("notes.list", "Lab notes, optionally of one design.", obj({"design": REF}), "read", notes_list),
        t("fab.export", "Write the printable parts (STL), bill of materials and assembly notes of a design into the workspace. Needs a human to confirm the session.", obj({"design": REF}, ["design"]), "confirm", fab_export_tool),
    ]
    return Registry(operation_tools() + hand)
