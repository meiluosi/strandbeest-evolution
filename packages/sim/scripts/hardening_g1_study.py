"""H2-01: preserve reproducible evidence for full-cohort and diagnostic G1 studies.

The sample generator, seed and audit thresholds are unchanged. Overrides are
explicit experimental inputs, never new production defaults. Every completed
case is checkpointed, including errors and full findings; a partial run cannot
be mistaken for a passing cohort. Refuses to overwrite existing evidence.

Example (candidate, not an accepted default):
  .venv/bin/python packages/sim/scripts/hardening_g1_study.py out.json \
      --overrides '{"solver":{"solref_time":0.0005}}' --workers 6
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import random
import subprocess
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import load_scenario, run, scenario_from_design
from strandbeest_sim.skeptic import (
    ENERGY_RESIDUAL,
    LOOP_OPEN_M,
    PENETRATION_M,
    STRIDE_TOLERANCE,
    audit,
    random_scenario,
)

ROOT = Path(__file__).resolve().parents[3]


def source_hashes() -> dict[str, str]:
    paths = [
        *sorted((ROOT / "packages/sim/src").rglob("*.py")),
        *sorted((ROOT / "packages/common/src").rglob("*.py")),
        ROOT / "schemas/scenario.schema.json",
        ROOT / "schemas/scenario-v1.schema.json",
        Path(__file__),
    ]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def one(job: tuple[int, dict, dict]) -> dict:
    case, design, overrides = job
    start = time.monotonic()
    row = {"case": case, "design": design, "overrides": overrides}
    try:
        scenario = scenario_from_design(Design(design), overrides)
        row["scenario"] = scenario.model_dump(mode="json", exclude_unset=True)
        assert load_scenario(row["scenario"]) == scenario
        result = run(scenario)
        findings = audit(result.scenario, result.metrics, result.series, result.stalled)
        row.update(
            metrics=result.metrics,
            stalled=bool(result.stalled),
            findings=[asdict(f) for f in findings],
            completed=True,
            simulated_s=float(result.t[-1]),
        )
    except Exception as exc:
        row.update(completed=False, error=f"{type(exc).__name__}: {exc}")
    row["wall_s"] = time.monotonic() - start
    return row


def checkpoint(path: Path, document: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--n", type=int, default=64)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overrides", type=json.loads, default={})
    parser.add_argument("--cases", type=int, nargs="+", help="Diagnostic subset only; never a full-cohort pass")
    args = parser.parse_args()
    if args.n < 1 or args.workers < 1:
        parser.error("n and workers must be positive")
    selected = set(range(args.n)) if args.cases is None else set(args.cases)
    if not selected or not selected <= set(range(args.n)):
        parser.error("cases must be a nonempty subset of range(n)")
    if not isinstance(args.overrides, dict):
        parser.error("overrides must be an object")
    if args.output.exists():
        parser.error(f"evidence already exists: {args.output}")

    base = json.loads((schema_dir() / "examples/design-jansen-small-6leg.json").read_text())
    rng = random.Random(args.seed)
    jobs = []
    for case in range(args.n):
        design, overrides = random_scenario(rng, base)
        if case not in selected:
            continue
        for section, values in args.overrides.items():
            overrides.setdefault(section, {}).update(values)
        jobs.append((case, design, overrides))
    doc = {
        "study": "H2-01",
        "evidence_level": "E0",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "mujoco": importlib.metadata.version("mujoco"),
        "numpy": importlib.metadata.version("numpy"),
        "source_hashes": source_hashes(),
        "n": args.n,
        "seed": args.seed,
        "selected_cases": sorted(selected),
        "workers": args.workers,
        "overrides": args.overrides,
        "thresholds": {
            "energy_residual_share": ENERGY_RESIDUAL,
            "loop_open_m": LOOP_OPEN_M,
            "penetration_m": PENETRATION_M,
            "stride_relative_error": STRIDE_TOLERANCE,
        },
        "complete": False,
        "full_cohort_pass": False,
        "g1_reference_cohort_pass": False,
        "rows": [],
    }
    with args.output.open("x") as output:
        json.dump(doc, output, indent=2)
    start = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(one, job) for job in jobs]
        for future in as_completed(futures):
            row = future.result()
            doc["rows"].append(row)
            doc["rows"].sort(key=lambda entry: entry["case"])
            checkpoint(args.output, doc)
            checks = [f["check"] for f in row.get("findings", [])]
            print(f"{len(doc['rows'])}/{len(jobs)} case {row['case']}: {row.get('error', checks or 'PASS')}", flush=True)
    doc["complete"] = True
    doc["wall_s"] = time.monotonic() - start
    bad = [row for row in doc["rows"] if not row["completed"] or row["findings"]]
    doc["summary"] = {
        "completed": sum(row["completed"] for row in doc["rows"]),
        "failed_cases": [row["case"] for row in bad],
        "findings": dict(Counter(f["check"] for row in doc["rows"] for f in row.get("findings", []))),
    }
    doc["full_cohort_pass"] = not bad and len(doc["rows"]) == args.n
    # A passing smaller sample or a different seed is useful evidence, but does
    # not close the specified 64-walker seed-1 acceptance gate.
    doc["g1_reference_cohort_pass"] = doc["full_cohort_pass"] and args.n == 64 and args.seed == 1
    final_hashes = source_hashes()
    doc["sources_changed_during_run"] = [p for p, h in doc["source_hashes"].items() if final_hashes.get(p) != h]
    checkpoint(args.output, doc)
    print(json.dumps(doc["summary"], indent=2))


if __name__ == "__main__":
    main()
