"""Content identity must fail closed without depending on git, mtime or a build label."""

import os
import shutil

import pytest

from strandbeest_common.implementation import ProcessImplementation


def snapshot(root, runtime=None):
    return ProcessImplementation(lambda: {p.name: p for p in root.iterdir() if p.is_file()},
                                 lambda: runtime if runtime is not None else {"python": "test"})


def test_content_identity_is_location_independent_and_not_a_version_label(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    (a / "source.py").write_text("value = 1\n")
    (a / "kernel.so").write_bytes(b"test-native-binary")
    shutil.copytree(a, b)
    before = snapshot(a).current()
    monkeypatch.setenv("STRANDBEEST_CODE_VERSION", "a-different-display-label")
    assert snapshot(b).current() == before
    assert before["status"] == "verified"
    assert set(before["manifest"]["files"]) == {"source.py", "kernel.so"}


@pytest.mark.parametrize("change", ["edit_same_size_mtime", "add", "delete", "native_bytes", "dependency"])
def test_runtime_drift_invalidates_existing_process_and_restart_gets_new_identity(tmp_path, change):
    source = tmp_path / "source.py"
    source.write_text("value = 1\n")
    native = tmp_path / "kernel.so"
    native.write_bytes(b"native-v1")
    runtime = {"numpy": "1.0"}
    process = snapshot(tmp_path, runtime)
    before = process.current()
    if change == "edit_same_size_mtime":
        stat = source.stat()
        source.write_text("value = 2\n")
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif change == "add":
        (tmp_path / "new.py").write_text("new = True\n")
    elif change == "delete":
        source.unlink()
    elif change == "native_bytes":
        native.write_bytes(b"native-v2")
    else:
        runtime["numpy"] = "2.0"
    assert process.current()["status"] == "unavailable"
    assert process.current()["reason"] == "implementation_changed_since_import"
    assert "implementation_hash" not in process.current()
    restarted = snapshot(tmp_path, runtime).current()
    assert restarted["status"] == "verified"
    assert restarted["implementation_hash"] != before["implementation_hash"]


def test_missing_files_and_incomplete_inventory_never_get_a_cache_identity(tmp_path):
    p = tmp_path / "missing.py"
    process = ProcessImplementation(lambda: {"source.py": p}, lambda: {"python": "test"})
    assert process.current()["reason"] == "implementation_unavailable"
    p.write_text("value = 1\n")
    # Recovery requires a new process, not assuming the new file was the loaded code.
    assert process.current()["status"] == "unavailable"
    assert snapshot(tmp_path).current()["status"] == "verified"
    assert ProcessImplementation(lambda: {}, lambda: {}).current()["status"] == "unavailable"


def test_identity_cannot_be_mutated_by_a_caller_and_invalidated_process_stays_invalid(tmp_path):
    p = tmp_path / "source.py"
    p.write_text("value = 1\n")
    process = snapshot(tmp_path)
    identity = process.current()
    identity["manifest"]["files"].clear()
    assert process.current()["manifest"]["files"]
    p.write_text("value = 2\n")
    assert process.current()["status"] == "unavailable"
    p.write_text("value = 1\n")
    assert process.current()["status"] == "unavailable"
