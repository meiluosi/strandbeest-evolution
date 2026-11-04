"""Subprocess helper: execute the real API from an isolated installed layout."""

import json
import os
import sys
from pathlib import Path

from strandbeest_api.pipeline import __file__ as pipeline_file
from strandbeest_common.schemas import schema_dir

from test_cache_identity import PAYLOAD, client_at, run_job

root, mode = Path(sys.argv[1]), sys.argv[2]
if mode == "edit-loaded-source":
    p = Path(pipeline_file)
    stat = p.stat()
    text = p.read_text()
    assert 'res.metrics["test_only_revision"] = 2' in text
    p.write_text(text.replace('res.metrics["test_only_revision"] = 2', 'res.metrics["test_only_revision"] = 3'))
    os.utime(p, ns=(stat.st_atime_ns, stat.st_mtime_ns))

with client_at(root) as client:
    first = run_job(client)
    second = run_job(client)
    history = client.get("/runs").json()
    # Old records remain readable after reindex even when they cannot be reused.
    for row in history:
        assert client.get(f"/runs/{row['id']}").status_code == 200
print(json.dumps({"first": first, "second": second, "pipeline_file": pipeline_file,
                  "schema_dir": str(schema_dir()), "run_count": len(history)}))
