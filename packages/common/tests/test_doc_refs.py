"""Q-04: the documentation reference checker passes on the repository and catches broken references."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_doc_refs.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_doc_refs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_doc_refs"] = module
    spec.loader.exec_module(module)
    return module


check = _load()


def make_repo(tmp_path: Path) -> Path:
    """A tiny repository with one script and one document."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "scripts" / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "package.json").write_text(
        '{"name": "tiny", "private": true, "scripts": {"check": "echo check"}}', encoding="utf-8"
    )
    return root


def test_repository_docs_are_consistent():
    assert check.main(["--root", str(ROOT)]) == 0


def test_broken_reference_fails_and_valid_reference_passes(tmp_path, capsys):
    root = make_repo(tmp_path)
    doc = root / "docs" / "NOTES.md"
    doc.write_text("Run `scripts/ok.py`, not `scripts/missing.py`.\n", encoding="utf-8")

    assert check.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "docs/NOTES.md:1: referenced path does not exist: scripts/missing.py" in out
    assert "scripts/ok.py" not in out

    doc.write_text("Run `scripts/ok.py`.\n", encoding="utf-8")
    assert check.main(["--root", str(root)]) == 0
    assert "broken reference" in capsys.readouterr().out


def test_urls_and_anchors_are_ignored(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "NOTES.md").write_text(
        "See https://example.com/missing.md, [link](https://example.com/x.md) and [section](#notes).\n",
        encoding="utf-8",
    )
    assert check.main(["--root", str(root)]) == 0


def test_broken_markdown_link_is_reported(tmp_path, capsys):
    root = make_repo(tmp_path)
    (root / "docs" / "ok.md").write_text("# ok\n", encoding="utf-8")
    (root / "docs" / "NOTES.md").write_text(
        "[good](ok.md) and [bad](missing.md)\n", encoding="utf-8"
    )
    assert check.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "docs/NOTES.md:1: referenced link target does not exist: missing.md" in out


def test_missing_script_in_a_command_is_reported(tmp_path, capsys):
    root = make_repo(tmp_path)
    (root / "docs" / "NOTES.md").write_text("```bash\npython scripts/ok.py\npython scripts/gone.py\n```\n", encoding="utf-8")
    assert check.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "referenced script does not exist: scripts/gone.py" in out
    assert "scripts/ok.py" not in out


def test_pnpm_script_must_exist(tmp_path, capsys):
    root = make_repo(tmp_path)
    (root / "docs" / "NOTES.md").write_text("```bash\npnpm check\npnpm nosuchscript\n```\n", encoding="utf-8")
    assert check.main(["--root", str(root)]) == 1
    assert "pnpm script not found: nosuchscript" in capsys.readouterr().out


def test_make_directory_and_target_must_exist(tmp_path, capsys):
    root = make_repo(tmp_path)
    (root / "hardware" / "firmware").mkdir(parents=True)
    (root / "hardware" / "firmware" / "Makefile").write_text("test:\n\techo test\n", encoding="utf-8")
    (root / "docs" / "NOTES.md").write_text("```bash\nmake -C hardware/firmware test\n```\n", encoding="utf-8")
    assert check.main(["--root", str(root)]) == 0

    (root / "docs" / "NOTES.md").write_text("```bash\nmake -C hardware/missing test\n```\n", encoding="utf-8")
    assert check.main(["--root", str(root)]) == 1
    assert "make directory does not exist: hardware/missing" in capsys.readouterr().out


def test_fenced_code_block_paths_are_illustrative_and_ignored(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "NOTES.md").write_text(
        "```\npackages/does/not/exist.ts\nscripts/ok.py\n```\n", encoding="utf-8"
    )
    assert check.main(["--root", str(root)]) == 0


def test_known_issue_is_tracked_but_only_fails_in_strict_mode(tmp_path, capsys):
    root = make_repo(tmp_path)
    doc = root / "docs" / "EDITOR.md"
    doc.write_text("[adr](adr/0003-missing.md)\n", encoding="utf-8")
    # a reference that does not exist is a hard failure
    assert check.main(["--root", str(root)]) == 1
    # ... unless it is tracked as a known issue
    key = ("docs/EDITOR.md", "adr/0003-missing.md")
    check.KNOWN_MISSING[key] = "renamed"
    try:
        assert check.main(["--root", str(root)]) == 0
        out = capsys.readouterr().out
        assert "known issue" in out and "adr/0003-missing.md" in out
        assert check.main(["--root", str(root), "--strict"]) == 1
    finally:
        check.KNOWN_MISSING.pop(key, None)


def test_a_pytest_node_id_is_checked_by_its_file(tmp_path, capsys):
    root = make_repo(tmp_path)
    (root / "packages" / "opt" / "tests").mkdir(parents=True)
    test_file = root / "packages" / "opt" / "tests" / "test_robust.py"
    test_file.write_text("def test_cvar():\n    pass\n", encoding="utf-8")
    (root / "docs" / "NOTES.md").write_text(
        "see `packages/opt/tests/test_robust.py::test_cvar`\n", encoding="utf-8"
    )
    assert check.main(["--root", str(root)]) == 0

    test_file.unlink()
    assert check.main(["--root", str(root)]) == 1
    assert "test_robust.py" in capsys.readouterr().out


def test_the_staging_area_is_not_documentation(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "_drafts").mkdir(parents=True)
    (root / "docs" / "_drafts" / "draft.md").write_text(
        "references `packages/does/not/exist.ts`\n", encoding="utf-8"
    )
    assert check.main(["--root", str(root)]) == 0
