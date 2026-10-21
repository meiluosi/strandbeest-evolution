#!/usr/bin/env python3
"""V-06: check a community Measurement submission and print its quality report.

A thin wrapper over ``strandbeest_calib.community.validate_submission``; all the rules live in
the package so that other callers (the API, the web UI) use exactly the same ones.

Usage:
    python scripts/validate_community_measurement.py <measurement.json> [--json] [--design <design.json>]

The design the submission claims to measure is looked up by its ``design_id`` in
``schemas/examples/`` and ``data/designs/`` unless ``--design`` names one.  Exit status is 0 when
the submission is accepted and 1 when it is rejected (a hard validation failure).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from strandbeest_calib.community import validate_submission

ROOT = Path(__file__).resolve().parents[1]
DESIGN_DIRS = (ROOT / "schemas" / "examples", ROOT / "data" / "designs")


def find_design(design_id: str) -> dict[str, Any] | None:
    """The design document with this id, or None when the repository does not know it."""
    for folder in DESIGN_DIRS:
        for path in sorted(folder.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict) and doc.get("id") == design_id and "linkage" in doc:
                return doc
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("measurement", help="the submitted Measurement JSON")
    ap.add_argument("--design", help="design document the measurement refers to (default: look it up by design_id)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON instead of text")
    args = ap.parse_args(argv)

    path = Path(args.measurement)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"{path} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    design = None
    if args.design:
        design = json.loads(Path(args.design).read_text(encoding="utf-8"))
    elif isinstance(doc, dict) and isinstance(doc.get("design_id"), str):
        design = find_design(doc["design_id"])

    report = validate_submission(doc, design=design)

    if args.json:
        print(json.dumps(report.asdict(), indent=2, ensure_ascii=False))
    else:
        print(f"submission: {path}")
        if design is None and isinstance(doc, dict):
            print(f"design {doc.get('design_id', '<none>')}: not found in the repository, so the stride was not checked against a leg reach")
        print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
