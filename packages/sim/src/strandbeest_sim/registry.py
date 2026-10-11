"""Name -> implementation registries. Scenarios refer to extensions by name; new ones register themselves."""

from __future__ import annotations

from typing import Any, Callable, Dict


class Registry:
    """`required_meta` names keyword arguments every registration must give (e.g. a drive's energy source); `choices` limits their values."""

    def __init__(self, kind: str, required_meta: tuple[str, ...] = (), choices: Dict[str, tuple] | None = None) -> None:
        self.kind = kind
        self.required_meta = required_meta
        self.choices = choices or {}
        self._items: Dict[str, Callable] = {}
        self._meta: Dict[str, dict[str, Any]] = {}

    def register(self, name: str, **meta: Any):
        missing = [k for k in self.required_meta if k not in meta]
        if missing:
            raise ValueError(f"{self.kind} '{name}' must declare {missing}")
        for k, allowed in self.choices.items():
            if k in meta and meta[k] not in allowed:
                raise ValueError(f"{self.kind} '{name}': {k}={meta[k]!r} is not one of {allowed}")

        def deco(fn: Callable) -> Callable:
            if name in self._items:
                raise ValueError(f"{self.kind} '{name}' already registered")
            self._items[name] = fn
            self._meta[name] = meta
            return fn

        return deco

    def meta(self, name: str) -> dict[str, Any]:
        self.get(name)  # raises the helpful error for unknown names
        return self._meta[name]

    def get(self, name: str) -> Callable:
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(f"unknown {self.kind} '{name}'; available: {sorted(self._items)}") from None

    def names(self) -> list[str]:
        return sorted(self._items)


terrains = Registry("terrain")
winds = Registry("wind")
# Where the energy comes from (docs/WIND.md section 2): "wind" (also wind-charged storage), "gravity", or "test_rig" (an electric
# servo used as an instrument, never part of a product result). A drive that does not declare it cannot be registered.
ENERGY_SOURCES = ("wind", "gravity", "test_rig")
drives = Registry("drive", required_meta=("energy_source",), choices={"energy_source": ENERGY_SOURCES})
metrics = Registry("metric")
