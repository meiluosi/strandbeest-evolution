#!/usr/bin/env python3
"""ADR-0009 trigger check: how many modules exist twice (TS and Python), do they all exist, and have a contract corpus?

Exit 1 when the trigger line is crossed (too many duplicated modules or recorded disagreement incidents) or a listed
file / corpus is missing, so the question 'should we move to one kernel?' is answered by data, not by feeling."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
doc = json.loads((root / "contracts" / "duplicated-modules.json").read_text())
problems = []
for m in doc["modules"]:
    for key in ("ts", "py", "corpus"):
        if not (root / m[key]).exists():
            problems.append(f"{m['name']}: {key} path missing: {m[key]}")
n = len(doc["modules"])
print(f"{n} duplicated module(s) (limit {doc['max_duplicated_modules']}), {doc['incidents_of_disagreement']} recorded disagreement incident(s)")
if n > doc["max_duplicated_modules"]:
    problems.append(f"trigger crossed: {n} duplicated modules > {doc['max_duplicated_modules']}; evaluate a single kernel (ADR-0009)")
if doc["incidents_of_disagreement"] >= 2:
    problems.append("trigger crossed: second disagreement incident; evaluate a single kernel (ADR-0009)")
for p in problems:
    print("PROBLEM:", p)
sys.exit(1 if problems else 0)
