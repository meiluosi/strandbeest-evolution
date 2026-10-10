"""The agent's working folder: designs with their operation logs, runs, lab notes and the audit log (all plain files)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from strandbeest_common import Design
from strandbeest_common.guard import default_problems
from strandbeest_common.ids import new_ulid
from strandbeest_common.migrate import migrate_any
from strandbeest_common.ops import History, make_op
from strandbeest_common.schemas import schema_dir
from strandbeest_fab import printable_problems


class ToolError(Exception):
    """A tool call that cannot be carried out; `code` is stable and machine-readable."""

    def __init__(self, code: str, message: str, data: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.data = code, message, data


GUARDS = (default_problems, printable_problems)


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        for sub in ("designs", "oplogs", "runs"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._histories: dict[str, History] = {}

    # ---- designs ---------------------------------------------------------------------------------------------
    def _doc_path(self, did: str) -> Path:
        return self.root / "designs" / f"{did}.json"

    def design_ids(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "designs").glob("*.json"))

    def resolve(self, ref: str) -> str:
        """Design id from an id or a (unique) name."""
        ids = self.design_ids()
        if ref in ids:
            return ref
        named = [i for i in ids if json.loads(self._doc_path(i).read_text())["name"] == ref]
        if len(named) == 1:
            return named[0]
        raise ToolError("unknown_design" if not named else "ambiguous_design", f"no single design '{ref}'; known: {ids}")

    def _save(self, did: str) -> None:
        h = self._histories[did]
        self._doc_path(did).write_text(json.dumps(h.design, indent=2))
        steps = h.steps
        (self.root / "oplogs" / f"{did}.json").write_text(json.dumps({"schema_version": 1, "design_id": did, "base": h.base, "steps": steps}))

    def history(self, ref: str) -> History:
        did = self.resolve(ref)
        if did not in self._histories:
            log = json.loads((self.root / "oplogs" / f"{did}.json").read_text())
            h = History(log["base"], GUARDS)
            for step in log["steps"]:
                h.commit_many(step)
            self._histories[did] = h
        return self._histories[did]

    def create(self, doc: dict[str, Any] | None = None, example: str | None = None, name: str | None = None) -> str:
        if doc is None:
            f = schema_dir() / "examples" / f"design-{example or 'jansen-small-6leg'}.json"
            if not f.exists():
                raise ToolError("unknown_example", f"no example '{example}'")
            doc = json.loads(f.read_text())
        d = Design(migrate_any(doc, "design")).doc  # validates, upgrades v1
        d = json.loads(json.dumps(d))
        old = d["id"]
        d["id"] = new_ulid()  # a created design is a new asset; the source is recorded as its parent
        d["parent"] = {"id": old}
        if name:
            d["name"] = name
        h = History(d, GUARDS)
        self._histories[d["id"]] = h
        self._save(d["id"])
        return d["id"]

    def apply(self, ref: str, op_type: str, args: dict[str, Any], actor: dict[str, str], reason: str) -> dict[str, Any]:
        h = self.history(ref)
        applied = h.commit(make_op(op_type, args, actor=actor, reason=reason))  # raises OpError / GuardError
        self._save(h.design["id"])
        return {"design_id": h.design["id"], "operation_id": h.ops[-1]["id"], "warnings": applied.warnings, "design": h.design}

    def undo(self, ref: str) -> dict[str, Any]:
        h = self.history(ref)
        ops = h.undo()
        self._save(h.design["id"])
        return {"undone": ops, "design": h.design}

    def redo(self, ref: str) -> dict[str, Any]:
        h = self.history(ref)
        ops = h.redo()
        self._save(h.design["id"])
        return {"redone": ops, "design": h.design}

    # ---- runs --------------------------------------------------------------------------------------------------
    def run_dir(self, rid: str) -> Path:
        p = self.root / "runs" / Path(rid).name
        if not (p / "run.json").exists():
            raise ToolError("unknown_run", f"no run '{rid}'")
        return p

    def run_ids(self) -> list[str]:
        return sorted(p.parent.name for p in (self.root / "runs").glob("*/run.json"))

    # ---- notes and audit -----------------------------------------------------------------------------------------
    def add_note(self, note: dict[str, Any]) -> None:
        with (self.root / "notes.jsonl").open("a") as f:
            f.write(json.dumps(note) + "\n")

    def notes(self) -> list[dict[str, Any]]:
        p = self.root / "notes.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def audit(self, entry: dict[str, Any]) -> None:
        with (self.root / "audit.jsonl").open("a") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **entry}, default=str) + "\n")

    def audit_log(self) -> list[dict[str, Any]]:
        p = self.root / "audit.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []
