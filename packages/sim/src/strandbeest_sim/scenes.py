"""Scene presets (flat, slope, step, bumps, wind, gusts, Mars, Titan, Venus, Moon), shared with the web player through
contracts/scenes.json. Each preset is a set of overrides in the flat scenario shape for `scenario_from_design`."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def _file() -> Path:
    for parent in Path(__file__).resolve().parents:
        f = parent / "contracts" / "scenes.json"
        if f.exists():
            return f
    raise FileNotFoundError("contracts/scenes.json not found; run from a checkout of the repository")


def presets() -> dict[str, dict[str, Any]]:
    return json.loads(_file().read_text())["scenes"]


def scene_overrides(name: str, wind_speed: float = 3.0, revolutions: float = 2.0, frame_rate: float = 30.0) -> dict[str, Any]:
    """Overrides for scenario_from_design that reproduce what the web player runs for scene `name`."""
    scenes = presets()
    if name not in scenes:
        raise KeyError(f"unknown scene '{name}'; available: {sorted(scenes)}")
    sc = scenes[name]
    ov = copy.deepcopy(sc["ov"])
    ov["run"] = {"settle": 0.5, "revolutions": revolutions, "frame_rate": frame_rate, **ov.get("run", {})}
    if sc.get("sail"):
        ov["drive"] = {"kind": "sail", **ov.get("drive", {})}
        ov["wind"] = {**ov.get("wind", {}), "speed": wind_speed}
        ov["run"] = {**ov["run"], "give_up_after": 6, "max_time": 30}
    return ov
