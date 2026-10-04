from __future__ import annotations

import argparse
import json
from pathlib import Path

from strandbeest_common import Design

from .export import export


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="strandbeest-fab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write STL, BOM and assembly notes for a Design")
    e.add_argument("design")
    e.add_argument("out")
    a = ap.parse_args(argv)
    mf = export(Design.load(a.design), Path(a.out))
    bad = [c for c in mf["checks"] if c["status"] == "fail"]
    warn = [c for c in mf["checks"] if c["status"] == "warn"]
    print(json.dumps({"parts": len(mf["parts"]), "layers_per_leg": mf["layers_per_leg"], "failed_checks": [c["name"] for c in bad], "warnings": [c["name"] for c in warn]}, indent=2))
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
