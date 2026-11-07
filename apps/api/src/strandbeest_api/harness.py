"""Minimal experiment protocol and dataset snapshot persistence for the Harness API."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from strandbeest_common.harness import (
    revision_digest,
    snapshot_digest,
    validate_dataset_snapshot,
    validate_experiment_revision,
)
from strandbeest_common.hashing import content_hash
from strandbeest_common.ids import new_ulid
from strandbeest_common.migrate import migrate_any
from strandbeest_common.schemas import validate


class HarnessError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _invalid(message: str) -> HarnessError:
    return HarnessError(422, "invalid_harness_document", message)


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(409, "harness_storage_invalid", f"cannot read authoritative document: {path.name}") from exc


def _exclusive_write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(doc, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise HarnessError(409, "immutable_asset_conflict", f"refusing to overwrite {path.name}") from exc


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


class HarnessStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.root / "harness.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS harness_schema_migrations (
                  version INTEGER PRIMARY KEY, applied TEXT NOT NULL);
                INSERT OR IGNORE INTO harness_schema_migrations(version, applied) VALUES (1, CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS harness_experiments (
                  id TEXT PRIMARY KEY, path TEXT NOT NULL, title TEXT NOT NULL,
                  current_revision INTEGER NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS harness_revisions (
                  id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, revision INTEGER NOT NULL,
                  path TEXT NOT NULL, digest TEXT NOT NULL, created TEXT NOT NULL,
                  UNIQUE(experiment_id, revision));
                CREATE TABLE IF NOT EXISTS harness_snapshots (
                  id TEXT PRIMARY KEY, path TEXT NOT NULL, digest TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS harness_lineage (
                  child_id TEXT NOT NULL, child_kind TEXT NOT NULL,
                  parent_id TEXT NOT NULL, parent_kind TEXT NOT NULL, relation TEXT NOT NULL,
                  PRIMARY KEY(child_id, child_kind, parent_id, parent_kind, relation));
                """
            )

    def _doc(self, table: str, asset_id: str, not_found: str) -> dict[str, Any]:
        allowed = {"experiments": "harness_experiments", "revisions": "harness_revisions", "snapshots": "harness_snapshots"}
        with self._lock:
            row = self._db.execute(f"SELECT path FROM {allowed[table]} WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise HarnessError(404, "harness_asset_not_found", not_found)
        return _load(self.root / row["path"])

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT path,current_revision FROM harness_experiments ORDER BY created DESC, id DESC").fetchall()
        return [{**_load(self.root / row["path"]), "current_revision": row["current_revision"]} for row in rows]

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        doc = self._doc("experiments", experiment_id, "no such experiment")
        with self._lock:
            current = self._db.execute("SELECT current_revision FROM harness_experiments WHERE id=?", (experiment_id,)).fetchone()
        return {**doc, "current_revision": current["current_revision"]}

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        return self._doc("revisions", revision_id, "no such experiment revision")

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        return self._doc("snapshots", snapshot_id, "no such dataset snapshot")

    def _asset(self, ref: Any, expected: str) -> dict[str, Any]:
        if not isinstance(ref, dict) or ref.get("kind") != expected or not isinstance(ref.get("id"), str) or not isinstance(ref.get("digest"), str):
            raise _invalid(f"invalid {expected} reference")
        asset_id, digest = self.asset_identity(ref["id"], expected)
        if ref["id"] != asset_id or ref["digest"] != digest:
            raise HarnessError(409, "asset_reference_mismatch", f"{expected} reference does not match its current immutable content")
        return {"kind": expected, "id": asset_id, "digest": digest}

    def asset_identity(self, ref: str, kind: str) -> tuple[str, str]:
        if kind == "dataset_snapshot":
            doc = self.get_snapshot(ref)
            validate_dataset_snapshot(doc)
            return doc["id"], doc["digest"]
        safe = Path(ref).name
        if kind == "design":
            candidates = [self.root / "designs" / f"{safe}.json"]
            candidates.extend(sorted((self.root / "designs").glob("*.json")))
            for path in candidates:
                if not path.is_file():
                    continue
                doc = migrate_any(_load(path), "design")
                if ref in (doc["id"], doc.get("name"), *doc.get("aliases", [])):
                    validate("design", doc)
                    return doc["id"], content_hash(doc)
        elif kind == "run":
            doc, _ = self.resolve_run(ref)
            return doc["id"], content_hash(doc)
        elif kind in ("measurement", "profile"):
            candidates = [self.root / f"{kind}s" / f"{safe}.json"]
            candidates.extend(sorted((self.root / f"{kind}s").glob("*.json")))
            for path in candidates:
                if not path.is_file():
                    continue
                doc = migrate_any(_load(path), kind)
                if ref in (doc["id"], doc.get("name"), *doc.get("aliases", [])):
                    validate(kind, doc)
                    return doc["id"], content_hash(doc)
        raise HarnessError(422, "unknown_asset_reference", f"cannot resolve {kind} reference {ref}")

    def resolve_run(self, ref: str) -> tuple[dict[str, Any], Path]:
        safe = Path(ref).name
        candidates = [self.root / "runs" / safe / "run.json"]
        candidates.extend(sorted((self.root / "runs").glob("*/run.json")))
        seen: set[Path] = set()
        for path in candidates:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            doc = migrate_any(_load(path), "run")
            if ref in (doc["id"], doc.get("name"), *doc.get("aliases", [])):
                validate("run", doc)
                return doc, path.parent
        raise HarnessError(422, "unknown_asset_reference", f"cannot resolve run reference {ref}")

    def _validate_refs(self, revision: dict[str, Any]) -> None:
        inputs = revision["inputs"]
        self._asset(inputs["design"], "design")
        for run in inputs["source_runs"]:
            self._asset(run, "run")
        if "dataset_snapshot" in inputs:
            self._asset(inputs["dataset_snapshot"], "dataset_snapshot")
        for condition in revision["conditions"]:
            if "design" in condition:
                self._asset(condition["design"], "design")
        if "scenario" in inputs and content_hash(inputs["scenario"]["document"]) != inputs["scenario"]["digest"]:
            raise HarnessError(409, "asset_reference_mismatch", "scenario snapshot digest does not match its frozen document")

    def create_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload.get("title"), str) or not payload["title"].strip():
            raise _invalid("experiment title is required")
        experiment_id = new_ulid()
        now = _now()
        experiment = {
            "schema_version": 1,
            "id": experiment_id,
            "title": payload["title"],
            "status": "draft",
            "current_revision": 1,
            "created": now,
        }
        revision = self._new_revision(experiment_id, 1, payload, now)
        self._validate_refs(revision)
        relative = Path("experiments") / experiment_id
        with self._lock:
            _exclusive_write(self.root / relative / "experiment.json", experiment)
            _exclusive_write(self.root / relative / "revisions" / f"{revision['id']}.json", revision)
            with self._db:
                self._db.execute(
                    "INSERT INTO harness_experiments(id,path,title,current_revision,created) VALUES(?,?,?,?,?)",
                    (experiment_id, str(relative / "experiment.json"), experiment["title"], 1, now),
                )
                self._index_revision(revision, relative / "revisions" / f"{revision['id']}.json")
        return {"experiment": experiment, "revision": revision}

    def _index_revision(self, revision: dict[str, Any], path: Path) -> None:
        self._db.execute(
            "INSERT INTO harness_revisions(id,experiment_id,revision,path,digest,created) VALUES(?,?,?,?,?,?)",
            (revision["id"], revision["experiment_id"], revision["revision"], str(path), revision["digest"], revision["created"]),
        )
        self._add_lineage(revision["experiment_id"], "experiment", revision["id"], "experiment_revision", "has_revision")
        for ref in [revision["inputs"]["design"], *revision["inputs"]["source_runs"]]:
            self._add_lineage(revision["id"], "experiment_revision", ref["id"], ref["kind"], "uses_input")
        if "dataset_snapshot" in revision["inputs"]:
            ref = revision["inputs"]["dataset_snapshot"]
            self._add_lineage(revision["id"], "experiment_revision", ref["id"], ref["kind"], "uses_input")
        for condition in revision["conditions"]:
            if "design" in condition:
                self._add_lineage(revision["id"], "experiment_revision", condition["design"]["id"], "design", "uses_condition_design")
        if "base_id" in revision:
            self._add_lineage(revision["id"], "experiment_revision", revision["base_id"], "experiment_revision", "derived_from")

    def _new_revision(self, experiment_id: str, number: int, payload: dict[str, Any], now: str) -> dict[str, Any]:
        try:
            conditions = [
                {
                    "id": new_ulid(),
                    "key": condition["key"],
                    "label": condition["label"],
                    "role": condition["role"],
                    **({"design": condition["design"]} if "design" in condition else {}),
                    "parameters": condition["parameters"],
                }
                for condition in payload["conditions"]
            ]
            by_key = {condition["key"]: condition["id"] for condition in conditions}
            trials = [
                {
                    "id": new_ulid(),
                    "condition_id": by_key[trial["condition_key"]],
                    "key": trial["key"],
                    "seed": trial["seed"],
                    "purpose": trial["purpose"],
                }
                for trial in payload["trials"]
            ]
            doc = {
                "schema_version": 1,
                "id": new_ulid(),
                "experiment_id": experiment_id,
                "revision": number,
                "question": payload["question"],
                "inputs": payload["inputs"],
                "conditions": conditions,
                "trials": trials,
                "evaluation_suite": payload["evaluation_suite"],
                "budget": payload["budget"],
                "permission_policy": {"mode": "manual_only", "requires_execution_authorization": True},
                "created": now,
            }
            if "base_id" in payload:
                doc["base_id"] = payload["base_id"]
            doc["digest"] = revision_digest(doc)
            validate_experiment_revision(doc)
            return doc
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid(str(exc)) from exc

    def create_revision(self, experiment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_id)
        base = self.get_revision(str(payload.get("base_id", "")))
        if base["experiment_id"] != experiment_id or base["revision"] != experiment["current_revision"]:
            raise HarnessError(409, "revision_base_conflict", "a revision must extend the experiment's current revision")
        revision = self._new_revision(experiment_id, base["revision"] + 1, {**payload, "base_id": base["id"]}, _now())
        self._validate_refs(revision)
        relative = Path("experiments") / experiment_id / "revisions" / f"{revision['id']}.json"
        with self._lock:
            _exclusive_write(self.root / relative, revision)
            with self._db:
                self._index_revision(revision, relative)
                self._db.execute(
                    "UPDATE harness_experiments SET current_revision=? WHERE id=?",
                    (revision["revision"], experiment_id),
                )
            experiment["current_revision"] = revision["revision"]
            _exclusive_write(self.root / "experiments" / experiment_id / f"experiment-{revision['revision']}.json", experiment)
        return revision

    def validate_revision(self, revision_id: str) -> dict[str, Any]:
        revision = self.get_revision(revision_id)
        try:
            validate_experiment_revision(revision)
        except ValueError as exc:
            raise HarnessError(409, "immutable_revision_changed", str(exc)) from exc
        self._validate_refs(revision)
        return {"ok": True, "revision_id": revision_id, "digest": revision["digest"], "execution_authorized": False}

    def create_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if payload.get("transforms", []):
                raise _invalid("fitted transforms are not supported by the minimal snapshot API")
            channels = payload["observation"]["channels"]
            sources = []
            for source in payload["sources"]:
                run, directory = self.resolve_run(source["run_id"])
                arrays_file = source.get("arrays_file", "arrays.npz")
                relative = Path(arrays_file)
                if relative.is_absolute() or ".." in relative.parts:
                    raise _invalid("arrays_file must stay inside its run directory")
                path = (directory / relative).resolve()
                if not path.is_relative_to(directory.resolve()) or not path.is_file():
                    raise _invalid("arrays_file does not name a readable file inside its run directory")
                with np.load(path, allow_pickle=False) as arrays:
                    lengths = []
                    for channel in channels:
                        if channel not in arrays:
                            raise _invalid(f"run {run['id']} does not contain channel {channel}")
                        array = arrays[channel]
                        if array.ndim < 1:
                            raise _invalid(f"channel {channel} has no sample dimension")
                        lengths.append(len(array))
                    if len(set(lengths)) != 1:
                        raise _invalid(f"run {run['id']} channels have inconsistent sample counts")
                sources.append(
                    {
                        "run": {"kind": "run", "id": run["id"], "digest": content_hash(run)},
                        "episode_id": run["id"],
                        "group_id": run["design_id"],
                        "arrays_file": relative.as_posix(),
                        "arrays_sha256": _file_digest(path),
                        "sample_count": lengths[0],
                        "channels": list(channels),
                    }
                )
            doc = {
                "schema_version": 1,
                "id": new_ulid(),
                "sources": sources,
                "observation": {"time_unit": "s", "channels": list(channels)},
                "split": {"group_by": "design_id", "assignments": payload["split"]["assignments"]},
                "transforms": [],
                "total_samples": sum(source["sample_count"] for source in sources),
                "created": _now(),
            }
            doc["digest"] = snapshot_digest(doc)
            validate_dataset_snapshot(doc)
        except HarnessError:
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise _invalid(str(exc)) from exc
        relative_path = Path("dataset-snapshots") / f"{doc['id']}.json"
        with self._lock:
            _exclusive_write(self.root / relative_path, doc)
            with self._db:
                self._db.execute(
                    "INSERT INTO harness_snapshots(id,path,digest,created) VALUES(?,?,?,?)",
                    (doc["id"], str(relative_path), doc["digest"], doc["created"]),
                )
                for source in doc["sources"]:
                    self._add_lineage(doc["id"], "dataset_snapshot", source["run"]["id"], "run", "contains_episode")
                    self._add_lineage(doc["id"], "dataset_snapshot", source["group_id"], "design", "grouped_by")
        return doc

    def validate_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.get_snapshot(snapshot_id)
        try:
            validate_dataset_snapshot(snapshot)
            for source in snapshot["sources"]:
                run, directory = self.resolve_run(source["run"]["id"])
                if content_hash(run) != source["run"]["digest"] or run["design_id"] != source["group_id"]:
                    raise HarnessError(409, "snapshot_source_changed", f"run {source['run']['id']} no longer matches the snapshot")
                path = (directory / source["arrays_file"]).resolve()
                if not path.is_relative_to(directory.resolve()) or not path.is_file() or _file_digest(path) != source["arrays_sha256"]:
                    raise HarnessError(409, "snapshot_source_changed", f"arrays for run {run['id']} no longer match the snapshot")
        except HarnessError:
            raise
        except ValueError as exc:
            raise HarnessError(409, "immutable_snapshot_changed", str(exc)) from exc
        return {"ok": True, "snapshot_id": snapshot_id, "digest": snapshot["digest"], "total_samples": snapshot["total_samples"]}

    def _add_lineage(self, child_id: str, child_kind: str, parent_id: str, parent_kind: str, relation: str) -> None:
        self._db.execute(
            "INSERT INTO harness_lineage(child_id,child_kind,parent_id,parent_kind,relation) VALUES(?,?,?,?,?)",
            (child_id, child_kind, parent_id, parent_kind, relation),
        )

    def lineage(self, asset_id: str) -> dict[str, Any]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM harness_lineage WHERE child_id=? OR parent_id=? ORDER BY relation,child_id,parent_id",
                (asset_id, asset_id),
            ).fetchall()
        return {"asset_id": asset_id, "edges": [dict(row) for row in rows]}


def register_harness_routes(app: FastAPI, store: HarnessStore) -> None:
    @app.exception_handler(HarnessError)
    async def harness_error(request: Request, exc: HarnessError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"code": exc.code, "message": exc.message, "retryable": exc.retryable, "request_id": new_ulid()},
        )

    @app.get("/api/harness/v1/experiments")
    def list_experiments() -> list[dict[str, Any]]:
        return store.list_experiments()

    @app.post("/api/harness/v1/experiments", status_code=201)
    def create_experiment(payload: dict[str, Any]) -> dict[str, Any]:
        return store.create_experiment(payload)

    @app.get("/api/harness/v1/experiments/{experiment_id}")
    def get_experiment(experiment_id: str) -> dict[str, Any]:
        return store.get_experiment(experiment_id)

    @app.get("/api/harness/v1/experiment-revisions/{revision_id}")
    def get_revision(revision_id: str) -> dict[str, Any]:
        return store.get_revision(revision_id)

    @app.post("/api/harness/v1/experiments/{experiment_id}/revisions", status_code=201)
    def create_revision(experiment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return store.create_revision(experiment_id, payload)

    @app.post("/api/harness/v1/experiment-revisions/{revision_id}/validate")
    def validate_revision(revision_id: str) -> dict[str, Any]:
        return store.validate_revision(revision_id)

    @app.post("/api/harness/v1/dataset-snapshots", status_code=201)
    def create_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        return store.create_snapshot(payload)

    @app.get("/api/harness/v1/dataset-snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: str) -> dict[str, Any]:
        return store.get_snapshot(snapshot_id)

    @app.post("/api/harness/v1/dataset-snapshots/{snapshot_id}/validate")
    def validate_snapshot(snapshot_id: str) -> dict[str, Any]:
        return store.validate_snapshot(snapshot_id)

    @app.get("/api/harness/v1/assets/{asset_id}/lineage")
    def get_lineage(asset_id: str) -> dict[str, Any]:
        return store.lineage(asset_id)
