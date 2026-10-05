"""E3-04: nothing in the UI may change the design except by committing an operation. The design lives in
apps/web-demo/src/editor.svelte.ts; everything else reads it through `view`/`editor.design` and writes through `edit`/`commit`."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "apps" / "web-demo" / "src"
ALLOWED = {"editor.svelte.ts"}
WRITES = [
    (re.compile(r"\beditor\.design\b[^;\n]*?(?<![=!<>])=(?!=)"), "assigns into editor.design"),
    (re.compile(r"\beditor\.design\.[\w.\[\]]+\s*(?:=(?!=)|\+\+|--)"), "mutates editor.design"),
    (re.compile(r"bind:value=\{(?:view|editor)\."), "binds an input straight to the design"),
    (re.compile(r"\bstructuredClone\(editor\.design\)\.[\w.]+\s*="), "mutates a copy and keeps it as the design"),
]


def test_the_ui_only_changes_the_design_through_operations():
    offenders = []
    for p in sorted(SRC.glob("*.svelte")) + sorted(SRC.glob("*.ts")):
        if p.name in ALLOWED:
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            for rx, why in WRITES:
                if rx.search(line):
                    offenders.append(f"{p.name}:{n}: {why}: {line.strip()}")
    assert offenders == []


def test_the_design_fields_the_ui_edits_are_all_covered_by_operations():
    # every editable control in the design tab calls an editor function; none of them is a bare assignment
    text = (SRC / "DesignTab.svelte").read_text()
    for needle in ("setLength(", "setProperty(", 'edit("array_legs"', "commit(ops)", "openDocument("):
        assert needle in text, needle
