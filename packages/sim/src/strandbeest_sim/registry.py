"""Name -> implementation registries. Scenarios refer to extensions by name; new ones register themselves."""

from __future__ import annotations

from typing import Callable, Dict


class Registry:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: Dict[str, Callable] = {}

    def register(self, name: str):
        def deco(fn: Callable) -> Callable:
            if name in self._items:
                raise ValueError(f"{self.kind} '{name}' already registered")
            self._items[name] = fn
            return fn

        return deco

    def get(self, name: str) -> Callable:
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(f"unknown {self.kind} '{name}'; available: {sorted(self._items)}") from None

    def names(self) -> list[str]:
        return sorted(self._items)


terrains = Registry("terrain")
drives = Registry("drive")
metrics = Registry("metric")
