#!/usr/bin/env python3
"""Regenerate contracts/ids/ulid-vectors.json (deterministic). Both language runners must reproduce every row."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/common/src"))
from strandbeest_common.ids import encode_ulid, legacy_ulid  # noqa: E402

rng = random.Random(20261006)
rows = []
edge = [(0, 0), (0, (1 << 80) - 1), ((1 << 48) - 1, 0), ((1 << 48) - 1, (1 << 80) - 1), (1, 1), (1791244800000, 0)]
for t, r in edge + [(rng.randrange(0, 1 << 48), rng.randrange(0, 1 << 80)) for _ in range(34)]:
    rows.append({"time_ms": t, "random_hex": f"{r:020x}", "ulid": encode_ulid(t, r)})
legacy = [
    {"kind": k, "key": key, "ulid": legacy_ulid(k, key)}
    for k, key in [
        ("design", "jansen-small-6leg"),
        ("design", "名字 with spaces/中文"),
        ("run", "25844b8f5918"),
        ("measurement", "rig-001"),
        ("profile", "calib-1"),
    ]
]
out = Path(__file__).with_name("ulid-vectors.json")
out.write_text(json.dumps({"_doc": "ULID encoding rows and deterministic legacy ids; regenerate with generate_ulid_vectors.py", "ulid": rows, "legacy": legacy}, ensure_ascii=False, indent=1) + "\n")
print("wrote", out)
