"""Scenario models. The source of truth is schemas/scenario.schema.json; the pydantic models are generated from it
(scripts/gen_models.py -> strandbeest_common.models.scenario). Defaults marked x-assumption in the schema are guesses,
not measurements. This module re-exports the generated classes under their historic names and adds YAML loading."""

from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml
from strandbeest_common.models.scenario import (
    Drive,
    Environment,
    Linkage,
    Run,
    Scenario,
    Solver,
    Terrain,
    Walker,
    Wind,
)

SCHEMA_VERSION = 1

__all__ = ["SCHEMA_VERSION", "Drive", "Environment", "Linkage", "Run", "Scenario", "Solver", "Terrain", "Walker", "Wind", "load_scenario"]


def load_scenario(source: Union[str, Path, dict]) -> Scenario:
    data = source if isinstance(source, dict) else yaml.safe_load(Path(source).read_text())
    return Scenario.model_validate(data)
