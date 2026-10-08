"""Scenario models. The source of truth is schemas/scenario.schema.json (schema v2: a World with Entities placed in it);
schemas/scenario-v1.schema.json is the flat shape (one walker, its environment, drive and solver in one object).

- `Scenario` is the public, v2 document. `load_scenario` accepts v2 or v1 (migrated on the fly).
- `SimConfig` is the flat shape the simulator runs on internally for a single walker; `sim_config` makes it from a v2 scenario.
  The conversion is lossless in both directions (strandbeest_common.scenario).

Defaults marked x-assumption in the schemas are guesses, not measurements."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union

import yaml
from strandbeest_common.models.scenario import Scenario
from strandbeest_common.models.scenario_v1 import (
    Drive,
    Environment,
    Linkage,
    Run,
    Solver,
    Terrain,
    Walker,
    Wind,
)
from strandbeest_common.models.scenario_v1 import ScenarioV1 as SimConfig
from strandbeest_common.scenario import flatten, to_v2

SCHEMA_VERSION = 2

__all__ = ["SCHEMA_VERSION", "Drive", "Environment", "Linkage", "Run", "Scenario", "SimConfig", "Solver", "Terrain", "Walker", "Wind", "load_scenario", "sim_config"]


def _doc(source: Union[str, Path, dict[str, Any]]) -> dict[str, Any]:
    return source if isinstance(source, dict) else yaml.safe_load(Path(source).read_text())


def load_scenario(source: Union[str, Path, dict[str, Any]]) -> Scenario:
    """A schema v2 scenario from a dict or a JSON/YAML file in either schema version."""
    doc = _doc(source)
    if "entities" not in doc:  # a flat v1 scenario (schema_version 1 or absent)
        doc = to_v2(doc)
    return Scenario.model_validate(doc)


def sim_config(sc: Union[Scenario, SimConfig, dict[str, Any]]) -> SimConfig:
    """The flat configuration the simulator runs on."""
    if isinstance(sc, SimConfig):
        return sc
    doc = sc.model_dump(mode="json") if isinstance(sc, Scenario) else sc
    return SimConfig.model_validate(flatten(doc))
