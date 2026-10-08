"""Schema v1 -> v2 migration (ADR-0001, E2-02): documents get stable ids and refer to each other by id, not by name.

v1 identified things by name: a Design by `name`, a Run and a Measurement by a free-text `id`, a Profile by `name`, and
runs and measurements pointed at a design with `design_name`. v2 gives every asset a ULID `id` and uses `design_id`.

Old documents stay readable: `migrate_any` upgrades a v1 document in memory, and the id it assigns is derived from the
kind and the old name (`legacy_ulid`), so it is the same on every machine and a reference resolves to the id of the
thing it names without a lookup table. `python -m strandbeest_common.migrate PATH...` rewrites whole data folders.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .ids import is_ulid, legacy_ulid
from .scenario import to_v2
from .schemas import validate

KINDS = ("design", "run", "measurement", "profile", "scenario")
TARGET_VERSION = 2


def detect_kind(doc: dict[str, Any]) -> str | None:
    if "manufacturing" in doc and "linkage" in doc:
        return "design"
    if "scenario" in doc and "metrics" in doc:
        return "run"
    if "channels" in doc and "conditions" in doc:
        return "measurement"
    if "parameters" in doc and "provenance" in doc:
        return "profile"
    if "entities" in doc or ("walker" in doc and "terrain" in doc and "solver" in doc):
        return "scenario"
    return None


def migrate_doc(kind: str, doc: dict[str, Any]) -> dict[str, Any]:
    """The v2 form of `doc` (a copy). A document that is already v2 is returned unchanged."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")
    doc = copy.deepcopy(doc)
    version = doc.get("schema_version", 1 if kind == "scenario" else None)
    if version == TARGET_VERSION:
        return doc
    if version != 1:
        raise ValueError(f"cannot migrate a {kind} with schema_version {version!r}")
    out: dict[str, Any] = {}
    if kind == "scenario":
        return to_v2(doc)  # validated by the v1 model it goes through; the v2 schema is checked by the tests
    if kind == "design":
        out = {"schema_version": 2, "id": legacy_ulid("design", doc["name"]), **{k: v for k, v in doc.items() if k != "schema_version"}}
    elif kind == "run":
        old = doc.pop("id")
        out = {"schema_version": 2, "id": legacy_ulid("run", old), "design_id": legacy_ulid("design", doc["design_name"])}
        out.update({k: v for k, v in doc.items() if k != "schema_version"})
        out["aliases"] = [old]
    elif kind == "measurement":
        old = doc.pop("id")
        out = {"schema_version": 2, "id": legacy_ulid("measurement", old), "name": old, "design_id": legacy_ulid("design", doc["design_name"])}
        out.update({k: v for k, v in doc.items() if k != "schema_version"})
        out["aliases"] = [old]
    elif kind == "profile":
        out = {"schema_version": 2, "id": legacy_ulid("profile", doc["name"]), **{k: v for k, v in doc.items() if k != "schema_version"}}
        prov = out["provenance"]
        prov["measurement_ids"] = [m if is_ulid(m) else legacy_ulid("measurement", m) for m in prov["measurement_ids"]]
    validate(kind, out)
    return out


def migrate_any(doc: dict[str, Any], kind: str | None = None) -> dict[str, Any]:
    kind = kind or detect_kind(doc)
    if kind is None:
        raise ValueError("cannot tell what kind of document this is")
    return migrate_doc(kind, doc)


# ---------------------------------------------------------------------------------------------------------------------
# Whole folders. Layout (see apps/api): designs/<name>.json, runs/<id>/run.json, measurements/<id>.json, profiles/<name>.json.
def _read(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text())


def _dump(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def plan(root: Path) -> list[dict[str, Any]]:
    """What migrating a data folder (or a folder of examples) would do. Nothing is written."""
    root = Path(root)
    steps: list[dict[str, Any]] = []
    files: list[tuple[str, Path]] = []
    for sub, kind in (("designs", "design"), ("measurements", "measurement"), ("profiles", "profile")):
        files += [(kind, p) for p in sorted((root / sub).glob("*.json"))] if (root / sub).is_dir() else []
    files += [("run", p) for p in sorted((root / "runs").glob("*/run.json"))] if (root / "runs").is_dir() else []
    layout = bool(files)  # a data folder renames run folders and measurement files after the new id
    if not files:  # a plain folder of documents, e.g. schemas/examples: files keep their names
        for p in sorted(root.glob("*.json")):
            kind = detect_kind(_read(p))
            if kind:
                files.append((kind, p))
    for kind, p in files:
        doc = _read(p)
        if doc.get("schema_version") == TARGET_VERSION:
            continue
        new = migrate_doc(kind, doc)
        target = p
        if not layout:
            pass
        elif kind == "run":
            target = p.parent.parent / new["id"] / "run.json"
        elif kind == "measurement":
            target = p.with_name(f"{new['id']}.json")
        steps.append({"kind": kind, "path": p, "target": target, "old_id": doc.get("id", doc.get("name")), "new_id": new["id"], "doc": new})
    return steps


def apply(root: Path, steps: list[dict[str, Any]], backup: bool = True) -> None:
    root = Path(root)
    backup_dir = root / "_backup_v1"
    for s in steps:
        src: Path = s["path"]
        if backup:
            dst = backup_dir / src.relative_to(root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        if s["target"] != src:
            if s["kind"] == "run":
                s["target"].parent.exists() and sys.exit(f"refusing to overwrite {s['target'].parent}")
                src.parent.rename(s["target"].parent)  # the run folder is named by the run id
            else:
                src.unlink()
        s["target"].write_text(_dump(s["doc"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Migrate v1 documents to v2 (stable ids). Dry run unless --write is given.")
    ap.add_argument("paths", nargs="+", type=Path, help="a data folder (designs/, runs/, ...) or a folder of documents")
    ap.add_argument("--write", action="store_true", help="rewrite the files (originals are copied to <folder>/_backup_v1)")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)
    total = 0
    for root in args.paths:
        steps = plan(root)
        total += len(steps)
        for s in steps:
            move = f" -> {s['target'].relative_to(root)}" if s["target"] != s["path"] else ""
            print(f"{'migrated' if args.write else 'would migrate'} {s['kind']:<11} {s['path'].relative_to(root)}{move}  id {s['old_id']!r} -> {s['new_id']}")
        if args.write:
            apply(root, steps, backup=not args.no_backup)
    print(f"{total} document(s) {'migrated' if args.write else 'to migrate (dry run; use --write)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
