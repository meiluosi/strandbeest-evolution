from __future__ import annotations

import argparse
import json

from . import load_scenario, run


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="strandbeest-sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a scenario file")
    r.add_argument("scenario")
    r.add_argument("--json", action="store_true", help="print metrics as JSON")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        res = run(load_scenario(a.scenario))
        out = {"name": res.scenario.name, "stalled": res.stalled, **res.metrics}
        print(json.dumps(out, indent=2) if a.json else "\n".join(f"{k}: {v}" for k, v in out.items()))


if __name__ == "__main__":
    main()
