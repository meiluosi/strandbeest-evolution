"""Persistent job queue on SQLite, plus a thread worker pool.

Why SQLite: one file, no extra service, survives restarts, enough for a single-machine lab. Jobs that were running when
the process died are marked failed on startup (we do not silently re-run a multi-minute simulation).
MuJoCo releases the GIL while stepping, so worker threads give real parallelism.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

Handler = Callable[["JobContext", dict[str, Any]], Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
              result TEXT, error TEXT, done INTEGER DEFAULT 0, total INTEGER DEFAULT 0, message TEXT DEFAULT '',
              cancel INTEGER DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created);
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, design_name TEXT, created TEXT, stalled INTEGER, metrics TEXT, ranges TEXT);
            """
        )

    # -- jobs -------------------------------------------------------------
    def create(self, kind: str, payload: dict[str, Any]) -> str:
        jid = uuid.uuid4().hex[:12]
        now = _now()
        with self._lock:
            self._db.execute(
                "INSERT INTO jobs(id, kind, status, payload, created, updated) VALUES (?,?,?,?,?,?)",
                (jid, kind, "queued", json.dumps(payload), now, now),
            )
        return jid

    def _row(self, r: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": r["id"], "kind": r["kind"], "status": r["status"],
            "result": json.loads(r["result"]) if r["result"] else None, "error": r["error"],
            "progress": {"done": r["done"], "total": r["total"], "message": r["message"]},
            "cancel_requested": bool(r["cancel"]), "created": r["created"], "updated": r["updated"],
        }

    def get(self, jid: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return self._row(r) if r else None

    def list(self, status: str | None = None, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM jobs", []
        conds = [(c, v) for c, v in (("status=?", status), ("kind=?", kind)) if v]
        if conds:
            q += " WHERE " + " AND ".join(c for c, _ in conds)
            args = [v for _, v in conds]
        with self._lock:
            rows = self._db.execute(q + " ORDER BY created DESC LIMIT ?", (*args, limit)).fetchall()
        return [self._row(r) for r in rows]

    def claim_next(self) -> tuple[str, str, dict[str, Any]] | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM jobs WHERE status='queued' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
            if not r:
                return None
            self._db.execute("UPDATE jobs SET status='running', updated=? WHERE id=?", (_now(), r["id"]))
        return r["id"], r["kind"], json.loads(r["payload"])

    def progress(self, jid: str, done: int, total: int, message: str = "") -> None:
        with self._lock:
            self._db.execute("UPDATE jobs SET done=?, total=?, message=?, updated=? WHERE id=?", (done, total, message, _now(), jid))

    def finish(self, jid: str, result: Any) -> None:
        with self._lock:
            self._db.execute("UPDATE jobs SET status='done', result=?, updated=? WHERE id=?", (json.dumps(result), _now(), jid))

    def fail(self, jid: str, error: str) -> None:
        with self._lock:
            self._db.execute("UPDATE jobs SET status='failed', error=?, updated=? WHERE id=?", (error, _now(), jid))

    def mark_cancelled(self, jid: str, result: Any = None) -> None:
        with self._lock:
            self._db.execute("UPDATE jobs SET status='cancelled', result=?, updated=? WHERE id=?",
                             (json.dumps(result) if result is not None else None, _now(), jid))

    def request_cancel(self, jid: str) -> bool:
        """Queued jobs are cancelled at once; running ones stop at their next checkpoint (sweeps check between points)."""
        with self._lock:
            r = self._db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
            if not r or r["status"] in ("done", "failed", "cancelled"):
                return False
            if r["status"] == "queued":
                self._db.execute("UPDATE jobs SET status='cancelled', cancel=1, updated=? WHERE id=?", (_now(), jid))
            else:
                self._db.execute("UPDATE jobs SET cancel=1, updated=? WHERE id=?", (_now(), jid))
        return True

    def is_cancelled(self, jid: str) -> bool:
        with self._lock:
            r = self._db.execute("SELECT cancel FROM jobs WHERE id=?", (jid,)).fetchone()
        return bool(r and r["cancel"])

    def recover(self) -> int:
        """Jobs left 'running' by a previous process cannot still be running: mark them failed."""
        with self._lock:
            cur = self._db.execute("UPDATE jobs SET status='failed', error='interrupted by a restart', updated=? WHERE status='running'", (_now(),))
        return cur.rowcount

    # -- run index --------------------------------------------------------
    def index_run(self, doc: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?)",
                (doc["id"], doc["design_name"], doc["provenance"].get("created", ""), int(doc.get("stalled", False)),
                 json.dumps(doc["metrics"]), json.dumps(doc.get("ensemble", {}).get("ranges")) if "ensemble" in doc else None),
            )

    def list_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM runs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "design_name": r["design_name"], "created": r["created"], "stalled": bool(r["stalled"]),
                 "metrics": json.loads(r["metrics"]), "ranges": json.loads(r["ranges"]) if r["ranges"] else None} for r in rows]

    def has_run(self, rid: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM runs WHERE id=?", (rid,)).fetchone() is not None


class JobContext:
    def __init__(self, store: JobStore, jid: str) -> None:
        self.store, self.id = store, jid

    def progress(self, done: int, total: int, message: str = "") -> None:
        self.store.progress(self.id, done, total, message)

    @property
    def cancelled(self) -> bool:
        return self.store.is_cancelled(self.id)


class Cancelled(Exception):
    def __init__(self, partial: Any = None) -> None:
        super().__init__("cancelled")
        self.partial = partial


class Workers:
    def __init__(self, store: JobStore, handlers: dict[str, Handler], n: int = 2, poll: float = 0.2) -> None:
        self.store, self.handlers, self.poll = store, handlers, poll
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self._loop, daemon=True, name=f"worker-{i}") for i in range(n)]

    def start(self) -> None:
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next()
            if job is None:
                time.sleep(self.poll)
                continue
            jid, kind, payload = job
            try:
                handler = self.handlers[kind]
                self.store.finish(jid, handler(JobContext(self.store, jid), payload))
            except Cancelled as c:
                self.store.mark_cancelled(jid, c.partial)
            except Exception as e:  # report to the client instead of losing it in the pool
                self.store.fail(jid, f"{type(e).__name__}: {e}")
