#!/usr/bin/env python3
"""CI check (E1-01): UI source must not contain CJK literals; user-visible text goes through apps/web-demo/src/i18n catalogs.

  python scripts/check_no_hardcoded_cjk.py [--root DIR] [--allowlist FILE]

Comments are ignored. Exit status 1 and a path:line list when a literal is found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CJK = re.compile(r"[　-〿一-鿿＀-￯]+")
COMMENTS = re.compile(r"<!--.*?-->|/\*.*?\*/|(?<![:\"'`\\])//[^\n]*", re.S)
SOURCES = ("*.svelte", "*.ts")
SRC_DIR = Path("apps/web-demo/src")


def blank_comments(text: str) -> str:
    """Replace comments with same-length whitespace (newlines kept) so line numbers survive."""
    return COMMENTS.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def scan(root: Path, allow: dict) -> list[str]:
    skip_files = set(allow.get("files", []))
    allowed = allow.get("strings", {})
    problems: list[str] = []
    for pattern in SOURCES:
        for path in sorted((root / SRC_DIR).rglob(pattern)):
            rel = path.relative_to(root).as_posix()
            if rel in skip_files:
                continue
            ok = set(allowed.get(rel, []))
            for n, line in enumerate(blank_comments(path.read_text(encoding="utf-8")).splitlines(), 1):
                for m in CJK.finditer(line):
                    if m.group(0) not in ok:
                        problems.append(f"{rel}:{n}: hard-coded CJK literal {m.group(0)!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--allowlist", type=Path, default=None)
    args = ap.parse_args(argv)
    allow_path = args.allowlist or args.root / "scripts" / "i18n-allowlist.json"
    allow = json.loads(allow_path.read_text()) if allow_path.exists() else {}
    problems = scan(args.root, allow)
    for p in problems:
        print(p)
    print(f"{len(problems)} hard-coded CJK literal(s)" if problems else "ok: no hard-coded CJK literals")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
