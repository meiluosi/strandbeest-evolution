"""Scenario schema v1 (flat) <-> v2 (World + Entities). E4-01.

v1 put one walker, its environment, drive and solver in one flat object. v2 separates what the world is (gravity, atmosphere,
wind, terrain) from what is placed in it (entities with a bag of components: a walker has a linkage, a body and a drive).
The simulator still runs on the flat shape internally for a single walker; `flatten` makes it from v2, `to_v2` makes v2 from v1.
The two functions are inverse on every document the schemas accept (tested), so no information is lost in either direction.
"""

from __future__ import annotations

import copy
from typing import Any

from .models.scenario_v1 import ScenarioV1

WALKER = "walker"


def to_v2(doc: dict[str, Any]) -> dict[str, Any]:
    """The schema v2 form of a flat v1 scenario (defaults made explicit)."""
    v1 = ScenarioV1.model_validate(doc).model_dump(mode="json")
    return {
        "schema_version": 2,
        "name": v1["name"],
        "world": {
            "gravity": v1["environment"]["gravity"],
            "atmosphere": {"air_density": v1["environment"]["air_density"]},
            "wind": v1["wind"],
            "terrain": v1["terrain"],
        },
        "entities": [{"name": WALKER, "kind": "walker", "components": {"linkage": v1["linkage"], "body": v1["walker"], "drive": v1["drive"]}}],
        "solver": v1["solver"],
        "run": v1["run"],
    }


def flatten(doc: dict[str, Any]) -> dict[str, Any]:
    """The flat v1 form of a scenario given as v1 or v2. v2 scenarios with other than one walker cannot be flattened (E4-04)."""
    if "entities" not in doc:
        return copy.deepcopy(doc)
    walkers = [e for e in doc["entities"] if e["kind"] == "walker"]
    if len(doc["entities"]) != 1 or len(walkers) != 1:
        raise ValueError("the simulator runs one walker per world for now (E4-04 adds more)")
    c = walkers[0]["components"]
    for need in ("linkage", "body", "drive"):
        if need not in c:
            raise ValueError(f"a walker entity needs the '{need}' component")
    w = doc.get("world", {})
    return {
        "schema_version": 1,
        "name": doc.get("name", "unnamed"),
        "linkage": copy.deepcopy(c["linkage"]),
        "walker": copy.deepcopy(c["body"]),
        "environment": {"gravity": w.get("gravity", 9.81), "air_density": w.get("atmosphere", {}).get("air_density", 1.2)},
        "wind": copy.deepcopy(w.get("wind", {})),
        "terrain": copy.deepcopy(w.get("terrain", {})),
        "drive": copy.deepcopy(c["drive"]),
        "solver": copy.deepcopy(doc.get("solver", {})),
        "run": copy.deepcopy(doc.get("run", {})),
    }
