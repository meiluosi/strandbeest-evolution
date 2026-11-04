"""Real process restarts and same-label/same-mtime edits, with no git metadata.

Copies the actual Python packages into a wheel-style import layout. Native and
third-party dependencies stay installed in the test environment. No repository
source, user's run store or installed package is modified.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import strandbeest_api
import strandbeest_common
import strandbeest_sim
from strandbeest_common.schemas import schema_dir


def test_new_algorithm_and_running_process_file_drift_cannot_reuse_old_results(tmp_path):
    installed = tmp_path / "installed"
    installed.mkdir()
    for module in (strandbeest_common, strandbeest_sim, strandbeest_api):
        shutil.copytree(Path(module.__file__).parent, installed / module.__name__,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(schema_dir(), installed / "schemas")
    assert not (installed / ".git").exists()
    pipeline = installed / "strandbeest_api/pipeline.py"
    source = pipeline.read_text()
    assert source.count("    res = sim_run(sc)\n") == 1
    pipeline.write_text(source.replace("    res = sim_run(sc)\n",
                                      '    res = sim_run(sc)\n    res.metrics["test_only_revision"] = 1\n'))
    env = {**os.environ, "PYTHONPATH": str(installed), "PYTHONDONTWRITEBYTECODE": "1",
           "STRANDBEEST_CODE_VERSION": "unchanged-release-label"}
    data = tmp_path / "data"

    def invoke(mode="normal"):
        proc = subprocess.run([sys.executable, str(Path(__file__).with_name("cache_process_probe.py")),
                               str(data), mode], cwd=installed, env=env, capture_output=True, text=True, timeout=45)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        result = json.loads(proc.stdout)
        assert Path(result["pipeline_file"]) == pipeline
        assert Path(result["schema_dir"]) == installed / "schemas"
        return result

    old = invoke()
    original = old["first"]
    assert old["second"]["provenance"]["cache_hit_from"] == original["id"]
    old_path = data / "runs" / original["id"] / "run.json"
    old_bytes = old_path.read_bytes()
    restarted = invoke()
    assert restarted["first"]["provenance"]["cache_hit_from"] == original["id"]

    # Same release label and preserved mtime/size: actual content must invalidate.
    stat = pipeline.stat()
    pipeline.write_text(pipeline.read_text().replace('res.metrics["test_only_revision"] = 1',
                                                    'res.metrics["test_only_revision"] = 2'))
    os.utime(pipeline, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert pipeline.stat().st_size == stat.st_size
    changed = invoke()
    new = changed["first"]
    assert new["metrics"]["test_only_revision"] == 2
    assert "cache_hit_from" not in new["provenance"]
    assert new["provenance"]["input_key"] != original["provenance"]["input_key"]
    assert new["provenance"]["code_version"] == original["provenance"]["code_version"]
    assert changed["second"]["provenance"]["cache_hit_from"] == new["id"]

    # Disk now says 3; this already-loaded process still computes revision 2.
    # It must neither hit revision 2's cache nor claim to have executed revision 3.
    drift = invoke("edit-loaded-source")
    for doc in (drift["first"], drift["second"]):
        assert doc["metrics"]["test_only_revision"] == 2
        assert "cache_hit_from" not in doc["provenance"]
        assert "input_key" not in doc["provenance"]
        assert doc["provenance"]["execution_identity"]["reason"] == "implementation_changed_since_import"
    assert drift["first"]["id"] != drift["second"]["id"]
    after_restart = invoke()
    last = after_restart["first"]
    assert last["metrics"]["test_only_revision"] == 3
    assert last["provenance"]["execution_identity"]["status"] == "verified"
    assert len({last["provenance"]["input_key"], new["provenance"]["input_key"],
                original["provenance"]["input_key"]}) == 3
    assert after_restart["second"]["provenance"]["cache_hit_from"] == last["id"]
    assert old_path.read_bytes() == old_bytes
