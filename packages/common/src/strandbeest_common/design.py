"""Design: the single document that drives simulation, fabrication and the UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from .linkage import LinkageSpec, load_spec
from .schemas import validate

# Material properties used to turn manufacturing parameters into simulation inputs. Typical datasheet-order values
# for FDM parts; real printed parts differ (infill, layer adhesion), so these are assumptions.
DENSITY_KG_M3 = {"PLA": 1240.0, "PETG": 1270.0}  # assumption: solid part; use infill_fraction to scale
INFILL_FRACTION = 0.6  # assumption: typical sparse infill raises/lowers effective density


class Design:
    def __init__(self, doc: dict[str, Any]) -> None:
        validate("design", doc)
        self.doc = doc

    @classmethod
    def load(cls, source: Union[str, Path, dict]) -> "Design":
        return cls(source if isinstance(source, dict) else json.loads(Path(source).read_text()))

    @property
    def name(self) -> str:
        return self.doc["name"]

    @property
    def spec(self) -> LinkageSpec:
        return load_spec(self.doc["linkage"])

    @property
    def mfg(self) -> dict[str, Any]:
        return self.doc["manufacturing"]

    @property
    def walker(self) -> dict[str, Any]:
        return self.doc["walker"]

    def bar_mass_per_m(self) -> float:
        """kg per metre of printed bar, from cross-section and material (assumption-driven)."""
        m = self.mfg
        area = (m["bar_width_mm"] * 1e-3) * (m["bar_thickness_mm"] * 1e-3)
        return DENSITY_KG_M3[m["material"]] * INFILL_FRACTION * area

    def to_scenario(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """A simulator scenario dict for this design on flat ground with its own drive."""
        w, d = self.walker, self.doc["drive"]
        sc: dict[str, Any] = {
            "schema_version": 1,
            "name": self.name,
            "linkage": {"spec": "design"},  # resolved by the caller (see strandbeest_sim.from_design)
            "walker": {
                "legs": w["legs"],
                "mass": w["body_mass_kg"] + 0.0,  # legs are added on top by the caller if wanted; see sim builder
                "unit": w["unit_m"],
                "direction": w["direction"],
                "tube_mass_per_m": self.bar_mass_per_m(),
                "lateral_spacing": w.get("lateral_spacing_m", 0.1),
                "body_length": w.get("body_length_m", 1.0),
                "foot_radius": 0.002,
                "pitch": "locked",
            },
            "drive": {"kind": "motor", "omega": d.get("motor_omega_rad_s", 2.0)},
        }
        if overrides:
            for k, v in overrides.items():
                if isinstance(v, dict):
                    sc.setdefault(k, {}).update(v)
                else:
                    sc[k] = v
        return sc
