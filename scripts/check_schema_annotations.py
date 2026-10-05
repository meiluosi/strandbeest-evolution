#!/usr/bin/env python3
"""Check that schemas carry the x- annotations required by schemas/ANNOTATIONS.md.

Usage: python scripts/check_schema_annotations.py [--strict] [schema.json ...]
Without --strict it only prints the missing list and exits 0. With --strict any missing annotation fails.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

NUMERIC = {"number", "integer"}
# Units a schema may declare (schemas/ANNOTATIONS.md). A typo in x-unit is a defect, so unknown values are reported.
UNITS = {
    "m", "mm", "kg", "s", "rad", "deg", "rad/s", "N", "N·m", "N·m/rad", "N·m·s/rad", "1/s²", "m/s", "m/s²",
    "kg/m", "kg/m³", "m²", "kg·m²", "Hz", "1", "count", "unit_m",
}


def is_numeric(node: dict) -> bool:
    t = node.get("type")
    types = set(t) if isinstance(t, list) else {t}
    return bool(types & NUMERIC) and "const" not in node and "enum" not in node


def walk(node, path: str, out: list[str]) -> None:
    if not isinstance(node, dict):
        return
    if "x-unit" in node and node["x-unit"] not in UNITS:
        out.append(f"{path}: unknown x-unit {node['x-unit']!r}")
    if is_numeric(node):
        if "x-unit" not in node:
            out.append(f"{path}: numeric field without x-unit")
    if node.get("x-assumption") and "x-source" not in node:
        out.append(f"{path}: x-assumption without x-source")
    for key in ("properties", "$defs"):
        for name, sub in (node.get(key) or {}).items():
            walk(sub, f"{path}/{name}" if path else name, out)
    for key in ("items", "additionalProperties"):
        sub = node.get(key)
        if isinstance(sub, dict):
            walk(sub, f"{path}[]" if key == "items" else f"{path}{{}}", out)
    for key in ("oneOf", "anyOf", "allOf"):
        for i, sub in enumerate(node.get(key) or []):
            walk(sub, f"{path}<{key}{i}>", out)


def check(path: Path) -> list[str]:
    out: list[str] = []
    walk(json.loads(path.read_text()), path.stem.replace(".schema", ""), out)
    return out


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    files = [Path(a) for a in argv if not a.startswith("--")] or sorted((Path(__file__).resolve().parents[1] / "schemas").glob("*.schema.json"))
    total = 0
    for f in files:
        missing = check(f)
        total += len(missing)
        for m in missing:
            print(("ERROR " if strict else "warn  ") + m)
    print(f"{total} annotation problem(s) in {len(files)} schema(s)")
    return 1 if (strict and total) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
