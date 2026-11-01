"""Parameter sweeps: a grid of simulator runs over named axes."""

from __future__ import annotations

import itertools
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from strandbeest_common import Design, JobDAG

from .jobs import Cancelled, JobContext
from .pipeline import loop_tolerance, simulate

MAX_POINTS = 60


def _set_path(doc: dict, path: str, value: Any) -> None:
    keys = path.split(".")
    cur = doc
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def expand(axes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cartesian product of axis values: [{path: value, ...}, ...]. Paths start with 'design.' or 'scenario.'."""
    if not axes:
        raise ValueError("a sweep needs at least one axis")
    for a in axes:
        if not str(a.get("path", "")).startswith(("design.", "scenario.")):
            raise ValueError(f"axis path must start with 'design.' or 'scenario.': {a.get('path')}")
        if not a.get("values"):
            raise ValueError(f"axis {a['path']} has no values")
    points = []
    for combo in itertools.product(*(a["values"] for a in axes)):
        pt: dict[str, Any] = {}
        for a, v in zip(axes, combo):
            pt[a["path"]] = v
            for extra in a.get("also", []):  # paths that must take the same value (e.g. foot and ground friction)
                if not str(extra).startswith(("design.", "scenario.")):
                    raise ValueError(f"axis path must start with 'design.' or 'scenario.': {extra}")
                pt[extra] = v
        points.append(pt)
    if len(points) > MAX_POINTS:
        raise ValueError(f"sweep has {len(points)} points; the limit is {MAX_POINTS}")
    return points


def run_sweep(ctx: JobContext, payload: dict[str, Any], runs_dir: Path, parallel: int = 3) -> dict[str, Any]:
    base_doc = payload["design"]
    Design(base_doc)  # validate the base design early
    points = expand(payload["axes"])
    base_overrides = payload.get("overrides") or {}

    dag = JobDAG()
    rows: list[dict[str, Any] | None] = [None] * len(points)

    def evaluate_point(i: int) -> dict[str, Any]:
        if ctx.cancelled:
            return {"point": points[i], "run_id": None, "metrics": {}, "valid": False}
        doc = json.loads(json.dumps(base_doc))
        ov = json.loads(json.dumps(base_overrides))
        ov.setdefault("run", {}).setdefault("frame_rate", 0)  # sweep points are not replayed unless asked
        for path, value in points[i].items():
            _set_path(doc if path.startswith("design.") else ov, path.split(".", 1)[1], value)
        try:
            run = simulate(Design(doc), runs_dir, ov)
            ctx.store.index_run(run)
            m = run["metrics"]
            ok = not run["stalled"] and m.get("max_loop_violation", 1.0) < loop_tolerance(Design(doc))
            row = {"point": points[i], "run_id": run["id"], "metrics": m, "valid": ok}
        except Exception as e:
            row = {"point": points[i], "run_id": None, "metrics": {}, "valid": False, "error": f"{type(e).__name__}: {e}"}
        rows[i] = row
        return row

    point_node_ids = []
    for i in range(len(points)):
        nid = f"point_{i}"
        dag.add_node(nid, evaluate_point, dependencies=(), resources={"cpu": 1}, i=i)
        point_node_ids.append(nid)

    def aggregate_summary() -> dict[str, Any]:
        return {"axes": payload["axes"], "rows": [r for r in rows if r is not None]}

    dag.add_node("summary", aggregate_summary, dependencies=point_node_ids, resources={"cpu": 1})

    ctx.progress(0, len(points), "starting")

    def _progress(done: int, total: int, msg: str) -> None:
        # progress count relative to sweep points
        pts_done = min(done, len(points))
        ctx.progress(pts_done, len(points), f"{pts_done}/{len(points)} points")

    dag.execute(max_workers=parallel, progress_cb=_progress, is_cancelled=lambda: ctx.cancelled)
    result = dag.nodes["summary"].result or aggregate_summary()

    if ctx.cancelled:
        raise Cancelled(result)
    return result
