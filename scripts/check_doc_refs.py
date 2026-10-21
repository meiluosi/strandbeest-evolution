#!/usr/bin/env python3
"""Q-04 doc/code consistency check: every repository path, link and command the documentation
mentions must exist on disk.

The check scans ``docs/**/*.md`` plus ``README.md``, ``README.en.md``, ``AGENTS.md`` and
``CLAUDE.md`` for three kinds of reference:

* backtick-quoted relative paths (``packages/core/src/index.ts``, ``scripts/test-python.sh``),
* Markdown links to relative local targets (``[x](docs/ROADMAP.md)``),
* shell commands that invoke repository scripts (``python scripts/foo.py``,
  ``pnpm --filter @strandbeest/web-demo build``, ``make -C hardware/firmware test``).

Ignored on purpose: http(s) URLs, pure anchors (``#section``), absolute filesystem paths,
template placeholders (anything containing ``<``, ``>``, ``{``, ``}``, ``*`` or ``...``) and the
illustrative path listings inside fenced code blocks.

Usage: python scripts/check_doc_refs.py [--root DIR] [--strict]

Exit 0 when every reference resolves, 1 with a ``file:line: message`` list otherwise.  ``--strict``
additionally fails on the references listed in ``KNOWN_MISSING`` (pre-existing doc bugs that are
tracked here until the documentation is corrected).  Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

DOC_GLOBS: tuple[str, ...] = (
    "docs/**/*.md",
    "README.md",
    "README.en.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
)
# Top-level entries that are never documentation targets (build output, caches, virtualenvs).
IGNORED_TOP_LEVEL = frozenset({".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "out"})
# Characters that mark a template placeholder instead of a real path.
PLACEHOLDER_CHARS = "<>{}*"
# Suffixes of files that a command may invoke as a script.
SCRIPT_SUFFIXES = frozenset({".sh", ".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"})
# pnpm/npm subcommands that are not package.json scripts.
PNPM_BUILTINS = frozenset(
    {
        "access", "add", "audit", "bin", "bugs", "cache", "ci", "config", "create", "dedupe", "deprecated",
        "doctor", "dlx", "docs", "env", "exec", "fund", "get", "help", "home", "i", "import", "init", "install",
        "link", "list", "login", "logout", "ls", "outdated", "owner", "pack", "ping", "prune", "profile",
        "publish", "remove", "repo", "rm", "root", "run", "search", "set", "shrinkwrap", "star", "start",
        "store", "team", "token", "uninstall", "unlink", "unpublish", "unstar", "update", "version", "view",
        "whoami", "why",
    }
)
# pnpm flags that swallow the next token as their value.
PNPM_VALUE_FLAGS = frozenset({"--filter", "-F", "--filter-prod", "--dir", "-C", "--workspace-root", "-w"})

# Pre-existing broken references, tracked here so the check stays green while the docs are
# corrected.  Key: (document path relative to the repo root, referenced text).  Value: where the
# thing actually lives now.  Remove an entry once the document is fixed.
#
# Empty on 2026-10-21: the five entries that were here (docs/EDITOR.md's ADR-0003 link and four
# moved scripts in docs/EXPERIMENTS.md) were corrected, so the strict mode now passes too.
KNOWN_MISSING: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class Problem:
    """One broken reference."""

    doc: str
    line: int
    message: str
    ref: str
    known: bool = False

    def format(self) -> str:
        return f"{self.doc}:{self.line}: {self.message}"


@dataclass
class Repo:
    """The repository facts the check needs: top-level anchors, scripts, workspace packages."""

    root: Path
    anchors: frozenset[str] = field(default_factory=frozenset)
    root_scripts: dict[str, str] = field(default_factory=dict)
    workspace: dict[str, Path] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> Repo:
        root = root.resolve()
        anchors = {
            p.name
            for p in root.iterdir()
            if p.name not in IGNORED_TOP_LEVEL and (not p.name.startswith(".") or p.name == ".github")
        }
        root_scripts: dict[str, str] = {}
        root_pkg = root / "package.json"
        if root_pkg.exists():
            root_scripts = dict(json.loads(root_pkg.read_text(encoding="utf-8")).get("scripts", {}))
        workspace: dict[str, Path] = {}
        for pattern in ("packages/*", "apps/*"):
            for pkg_dir in sorted(root.glob(pattern)):
                pkg_json = pkg_dir / "package.json"
                if not pkg_json.exists():
                    continue
                name = json.loads(pkg_json.read_text(encoding="utf-8")).get("name")
                if name:
                    workspace[name] = pkg_json
        return cls(root=root, anchors=frozenset(anchors), root_scripts=root_scripts, workspace=workspace)


def doc_files(root: Path) -> list[Path]:
    """All Markdown files the check owns, in a stable order."""
    seen: dict[Path, None] = {}
    for pattern in DOC_GLOBS:
        for path in root.glob(pattern):
            seen[path] = None
    return sorted(p for p in seen if not is_staging(p, root))


def is_staging(path: Path, root: Path) -> bool:
    """True for the temporary staging area ``docs/_drafts/``.

    Sections are drafted there and merged into ``docs/EXPERIMENTS.md`` before they are committed, so the
    drafts are a work area, not documentation: a half-written draft must not fail the build."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return False
    return rel.startswith("docs/_drafts/")


def has_placeholder(text: str) -> bool:
    """True when the text contains a template placeholder (``<x>``, ``{x}``, ``*``, ``...``)."""
    return any(c in text for c in PLACEHOLDER_CHARS) or "..." in text


def normalise(token: str) -> str:
    """Strip a leading ``./`` so ``./scripts/x.sh`` and ``scripts/x.sh`` compare equal."""
    return re.sub(r"^\./", "", token)


def is_anchored(token: str, repo: Repo) -> bool:
    """True when the first segment of the path is a real top-level entry of the repository.

    Only anchored paths are checked: a bare name (``winds.py``) or a package-relative path
    (``backends/mujoco_backend.py``) cannot be resolved without guessing.
    """
    first = normalise(token).split("/", 1)[0]
    return first in repo.anchors


def looks_like_path(token: str) -> bool:
    """True when a backtick span looks like a concrete relative path to a file or directory."""
    if not token or has_placeholder(token):
        return False
    if any(c.isspace() for c in token):
        return False
    if token.startswith(("#", "/", "~", "-", "$", ">")):
        return False
    if "://" in token:
        return False
    if "/" not in token:
        return False
    last = token.rstrip("/").rsplit("/", 1)[-1]
    if not token.endswith("/") and "." not in last:
        # Extension-less reference: could be a planned package (``apps/web``) or a module name.
        return False
    return True


def resolves(repo: Repo, doc_path: Path, rel: str) -> bool:
    """True when the reference exists, either from the repository root or next to the document."""
    rel = normalise(rel)
    if (repo.root / rel).exists():
        return True
    return (doc_path.parent / rel).exists()


# --- Markdown lexing ------------------------------------------------------------------------


def fence_marker(line: str) -> str | None:
    """The fence marker of an opening code fence, or None."""
    m = re.match(r"^ {0,3}(`{3,}|~{3,})[ \t]*(\S*)", line)
    if not m:
        return None
    if m.group(1)[0] == "`" and "`" in m.group(2):
        return None
    return m.group(1)


def closes_fence(line: str, marker: str) -> bool:
    """True when the line closes the given fence."""
    m = re.match(r"^ {0,3}(`{3,}|~{3,})[ \t]*$", line)
    return bool(m) and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker)


def code_spans(line: str) -> Iterator[str]:
    """The inline code spans of a line, without the backticks."""
    for m in re.finditer(r"(?P<ticks>`+)(?P<body>[^\n]*?)(?P=ticks)", line):
        body = m.group("body")
        if body:
            yield body


def link_targets(line: str) -> Iterator[str]:
    """The targets of the Markdown links of a line (images included)."""
    for m in re.finditer(r"!?\[[^\]\n]*\]\(\s*<?([^)>\s]+)>?", line):
        yield m.group(1)


# --- Individual rules ------------------------------------------------------------------------


def check_path_ref(repo: Repo, doc: str, doc_path: Path, line: int, token: str, problems: list[Problem]) -> None:
    """Rule 1: a backtick-quoted path must exist."""
    if not looks_like_path(token) or not is_anchored(token, repo):
        return
    # A pytest node id (``path/to/test_x.py::test_name``) names a file and a test inside it: check the file.
    target = token.split("::", 1)[0]
    if not target:
        return
    if resolves(repo, doc_path, target):
        return
    problems.append(Problem(doc, line, f"referenced path does not exist: {target}", target))


def check_link_ref(repo: Repo, doc: str, doc_path: Path, line: int, target: str, problems: list[Problem]) -> None:
    """Rule 2: a Markdown link to a local file must exist."""
    if target.startswith(("http://", "https://", "mailto:", "//")) or target.startswith(("#", "/")):
        return
    if has_placeholder(target):
        return
    path = target.split("#", 1)[0]
    if not path:
        return
    if resolves(repo, doc_path, path):
        return
    problems.append(Problem(doc, line, f"referenced link target does not exist: {target}", target))


def check_script_token(repo: Repo, doc: str, doc_path: Path, line: int, token: str, problems: list[Problem]) -> None:
    """Rule 3a: a script path inside a command must exist."""
    if not token or token.startswith("-") or "=" in token:
        return
    if has_placeholder(token) or token.startswith(("/", "http:", "https:")):
        return
    if Path(token).suffix not in SCRIPT_SUFFIXES:
        return
    if not is_anchored(token, repo):
        return
    if resolves(repo, doc_path, token):
        return
    problems.append(Problem(doc, line, f"referenced script does not exist: {token}", token))


def check_pnpm(repo: Repo, doc: str, line: int, tokens: list[str], problems: list[Problem]) -> None:
    """Rule 3b: ``pnpm <script>`` and ``pnpm --filter <package> <script>`` must exist."""
    i = 1
    package: str | None = None
    while i < len(tokens):
        token = tokens[i]
        if has_placeholder(token):
            return
        if token in PNPM_VALUE_FLAGS:
            if i + 1 >= len(tokens) or has_placeholder(tokens[i + 1]):
                return
            if token in ("--filter", "-F", "--filter-prod"):
                package = tokens[i + 1]
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        break
    rest = tokens[i:]
    if not rest:
        return
    head = rest[0]
    if head in PNPM_BUILTINS or head.startswith("-"):
        return
    script = rest[1] if head == "run" and len(rest) > 1 else head
    if not script or has_placeholder(script):
        return
    if package is not None:
        pkg_json = repo.workspace.get(package)
        if pkg_json is None:
            problems.append(Problem(doc, line, f"pnpm workspace package not found: {package}", package))
            return
        scripts = json.loads(pkg_json.read_text(encoding="utf-8")).get("scripts", {})
        if script not in scripts:
            problems.append(Problem(doc, line, f"pnpm script not found in {package}: {script}", script))
        return
    if script not in repo.root_scripts:
        problems.append(Problem(doc, line, f"pnpm script not found: {script}", script))


def check_make(repo: Repo, doc: str, line: int, tokens: list[str], problems: list[Problem]) -> None:
    """Rule 3c: ``make -C <dir> [target]`` must point at a real directory with a Makefile."""
    for i, token in enumerate(tokens):
        if token != "-C" or i + 1 >= len(tokens):
            continue
        directory = tokens[i + 1]
        if has_placeholder(directory) or directory.startswith("/"):
            continue
        if not (repo.root / directory).is_dir():
            problems.append(Problem(doc, line, f"make directory does not exist: {directory}", directory))
            continue
        makefile = repo.root / directory / "Makefile"
        if not makefile.exists():
            problems.append(Problem(doc, line, f"no Makefile in {directory}", directory))
            continue
        text = makefile.read_text(encoding="utf-8")
        if re.search(r"^\s*-?include\b", text, re.M):
            continue
        targets = set(re.findall(r"^([A-Za-z0-9_.-]+):", text, re.M))
        for target in tokens[i + 2 :]:
            if target.startswith("-") or "=" in target or has_placeholder(target):
                continue
            if target not in targets:
                problems.append(Problem(doc, line, f"make target not found in {directory}: {target}", target))


def check_command(repo: Repo, doc: str, doc_path: Path, line: int, text: str, problems: list[Problem]) -> None:
    """Rule 3: a shell command must only invoke scripts that exist."""
    for part in re.split(r"&&|\|\||;|\|", text):
        tokens = [t.strip("'\"") for t in part.split()]
        if not tokens:
            continue
        verb = tokens[0]
        if verb in ("pnpm", "npm"):
            check_pnpm(repo, doc, line, tokens, problems)
        elif verb == "make":
            check_make(repo, doc, line, tokens, problems)
        elif verb == "cd" and len(tokens) > 1:
            target = tokens[1]
            if "/" in target and is_anchored(target, repo) and not resolves(repo, doc_path, target):
                problems.append(Problem(doc, line, f"referenced directory does not exist: {target}", target))
        for token in tokens:
            check_script_token(repo, doc, doc_path, line, token, problems)


# --- Driver ---------------------------------------------------------------------------------


def check_file(repo: Repo, path: Path, problems: list[Problem]) -> None:
    """Check one Markdown file."""
    doc = path.relative_to(repo.root).as_posix()
    lines = path.read_text(encoding="utf-8").splitlines()
    in_fence = False
    marker = ""
    for number, line in enumerate(lines, 1):
        if in_fence:
            if closes_fence(line, marker):
                in_fence = False
            else:
                # Inside a code block only commands are checked: path listings are illustrative.
                check_command(repo, doc, path, number, line, problems)
            continue
        opening = fence_marker(line)
        if opening:
            in_fence = True
            marker = opening
            continue
        for span in code_spans(line):
            if not has_placeholder(span):
                # A span that holds a template placeholder is not a path reference.
                check_path_ref(repo, doc, path, number, span, problems)
            check_command(repo, doc, path, number, span, problems)
        for target in link_targets(line):
            check_link_ref(repo, doc, path, number, target, problems)


def check_repo(repo: Repo) -> list[Problem]:
    """Check every document and return the problems (known issues included, flagged as such)."""
    problems: list[Problem] = []
    seen: set[tuple[str, int, str]] = set()
    for path in doc_files(repo.root):
        check_file(repo, path, problems)
    unique: list[Problem] = []
    for problem in problems:
        key = (problem.doc, problem.line, problem.ref)
        if key in seen:
            continue
        seen.add(key)
        known = (problem.doc, problem.ref) in KNOWN_MISSING
        unique.append(Problem(problem.doc, problem.line, problem.message, problem.ref, known))
    return unique


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check that documentation references exist in the repository.")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root")
    ap.add_argument("--strict", action="store_true", help="also fail on the tracked known issues")
    args = ap.parse_args(argv)
    repo = Repo.load(args.root)
    problems = check_repo(repo)
    known = [p for p in problems if p.known]
    real = [p for p in problems if not p.known]
    for problem in real:
        print(problem.format())
    for problem in known:
        note = KNOWN_MISSING[(problem.doc, problem.ref)]
        print(f"{problem.doc}:{problem.line}: known issue: {problem.message} ({note})")
    files = doc_files(repo.root)
    print(f"{len(real)} broken reference(s) in {len(files)} document(s)")
    if known:
        print(f"{len(known)} known issue(s) tracked in scripts/check_doc_refs.py (use --strict to fail on them)")
    return 1 if (real or (args.strict and known)) else 0


if __name__ == "__main__":
    sys.exit(main())
