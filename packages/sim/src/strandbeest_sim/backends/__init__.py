"""Physics backends. A backend module registers itself under a name; `make_backend` builds one."""

from __future__ import annotations

from ..registry import Registry

backends = Registry("physics backend")


def make_backend(name: str = "mujoco"):
    from . import mujoco_backend  # noqa: F401  (registers "mujoco"; imported lazily so the engine is only loaded when used)

    return backends.get(name)()
