"""Identity of the loaded simulation path; runtime extensions disable reuse.

File manifests handle installed implementations. This additional process-local
guard detects replaced functions/methods, constants and plugin registrations;
injected observers must not silently reuse results of the unmodified pipeline.
It is a cache guard, not a security boundary against arbitrary memory mutation.
"""

from __future__ import annotations

import json
import sys
from types import FunctionType, ModuleType
from typing import Any

from strandbeest_common.implementation import PROCESS_IMPLEMENTATION, unavailable_identity
from strandbeest_sim.registry import drives, metrics, terrains, winds

_modules: tuple[ModuleType, ...] = ()
_sealed: dict[str, Any] | None = None


def _functions(value: Any) -> Any:
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    if isinstance(value, property):
        return tuple(_functions(f) for f in (value.fget, value.fset, value.fdel))
    if isinstance(value, FunctionType):
        return value, value.__code__
    return None


def _bindings() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for module in _modules:
        for name, value in list(vars(module).items()):
            key = f"{module.__name__}.{name}"
            functions = _functions(value)
            if functions is not None:
                out[key] = functions
            elif isinstance(value, type) and value.__module__.startswith(("strandbeest_common", "strandbeest_sim")):
                out[key] = {k: f for k, v in vars(value).items() if (f := _functions(v)) is not None}
            elif name.isupper():
                try:
                    out[key] = json.dumps(value, sort_keys=True)
                except (TypeError, ValueError):
                    pass
    for registry in (drives, metrics, terrains, winds):
        out[f"registry:{registry.kind}"] = (
            dict(registry._items), json.dumps(registry._meta, sort_keys=True))
    return out


def seal_runtime_bindings() -> None:
    """Called once, after pipeline import has defined its operations."""
    global _modules, _sealed
    if _sealed is not None:
        return
    _modules = tuple(m for name, m in list(sys.modules.items()) if m is not None and
                     (name.startswith(("strandbeest_common", "strandbeest_sim")) or
                      name == "strandbeest_api.pipeline"))
    _sealed = _bindings()


def execution_identity() -> dict[str, Any]:
    if _sealed is None or _bindings() != _sealed:
        return unavailable_identity("runtime_bindings_changed")
    return PROCESS_IMPLEMENTATION.current()
