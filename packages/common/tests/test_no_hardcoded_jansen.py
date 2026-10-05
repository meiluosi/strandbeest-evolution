"""E3-01: the viewer, sliders, optimiser genome and 3D preview derive from the LinkageSpec. Jansen's names and lengths may
only appear in the file that defines his leg, the default starting design, and the reproduction experiments."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BANNED = re.compile(r"JANSEN_PARAM_NAMES|JansenParams|JANSEN_LENGTHS|genomeToParams|paramsToGenome")
FOOT_LITERAL = re.compile(r"""(?:\bbar\.b\s*===\s*|\bp\.F\b|\b\w+\.b\s*===\s*)["']F["']|\bp\.F\b""")
ALLOWED = {
    "packages/core/src/jansen.ts",  # defines Jansen's leg and its genome helpers
    "packages/core/src/genome.ts",  # JANSEN_SPACE: his 13 lengths as a ready-made search space (genomeSpace works for any spec)
    "packages/core/src/index.ts",  # re-exports it
}


def sources():
    for base in ("apps/web-demo/src", "packages/core/src"):
        for p in sorted((ROOT / base).rglob("*")):
            rel = p.relative_to(ROOT).as_posix()
            if p.suffix in (".ts", ".svelte") and ".test." not in p.name and "generated" not in rel and rel not in ALLOWED:
                yield rel, p.read_text()


def test_no_jansen_names_outside_the_file_that_defines_the_leg():
    offenders = [f"{rel}:{n}: {line.strip()}" for rel, text in sources() for n, line in enumerate(text.splitlines(), 1) if BANNED.search(line)]
    assert offenders == []


def test_no_hardcoded_foot_id():
    offenders = [rel for rel, text in sources() if FOOT_LITERAL.search(text)]
    assert offenders == []
