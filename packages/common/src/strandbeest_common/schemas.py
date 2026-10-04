"""Load and validate the platform's JSON documents against the schemas in <repo>/schemas."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

NAMES = ("design", "measurement", "profile", "run")


def schema_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "schemas"
        if (cand / "design.schema.json").exists():
            return cand
    raise FileNotFoundError("schemas/ directory not found next to the package; run from a checkout of the repository")


@lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    if name not in NAMES:
        raise KeyError(f"unknown schema '{name}'; available: {NAMES}")
    schema = json.loads((schema_dir() / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate(name: str, doc: Any) -> None:
    """Raise ValueError listing every violation (path: message)."""
    errors = sorted(validator(name).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        raise ValueError(f"invalid {name}:\n" + "\n".join(f"  {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors))
