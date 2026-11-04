"""Process-bound implementation identity for simulation caches (ADR-0004).

Capture installed bytes before importing the project implementation. Never refresh
that snapshot inside a running process: edited files may no longer describe its
loaded code. Recheck the entire inventory, including additions/deletions, before
cache use and after computation. Unverifiable installs can still simulate, but
their results must not enter the reusable cache.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Callable

KEY_FORMAT = 2
# Covers signed energy-v3, observation-v3, events, evidence and the ensemble postprocessor.
# Content hashes also invalidate changes whose author forgets to bump this label.
SIMULATION_SEMANTICS = "beest-run/contact-v3-energy-v3-observation-v3-events-v1-evidence-v2-ensemble-v1-audit-v2-k2-contact-v4-k2-work-v1-k2-inertia-v1"
PACKAGES = ("strandbeest_common", "strandbeest_sim", "strandbeest_api", "beest_kernel")
DEPENDENCIES = ("beest-kernel", "mujoco", "numpy", "scipy", "pydantic", "pydantic-core", "pyarrow", "jsonschema", "PyYAML")


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def installed_files() -> dict[str, Path]:
    """Location-independent names for actual installed code/data, never git HEAD.

    API wheels still need the existing external schemas directory. Both a wheel
    installation with that directory and the checkout/container layout work.
    A missing native kernel or schema is not assigned a plausible placeholder.
    """
    files: dict[str, Path] = {}
    for name in PACKAGES:
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin or not spec.submodule_search_locations:
            raise FileNotFoundError(name)
        roots = list(spec.submodule_search_locations)
        if len(roots) != 1:
            raise ValueError("ambiguous package installation")
        root = Path(roots[0])
        if not (root / "__init__.py").is_file():
            raise FileNotFoundError(name)
        native = False
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if "__pycache__" in rel.parts or not path.is_file():
                continue
            if path.suffix in (".py", ".json", ".so", ".pyd", ".dylib"):
                files[f"{name}/{rel.as_posix()}"] = path
                native |= path.suffix in (".so", ".pyd")
        if name == "beest_kernel" and not native:
            raise FileNotFoundError("native kernel")
    # Same lookup contract as schemas.schema_dir(), without importing common.
    for parent in Path(__file__).resolve().parents:
        root = parent / "schemas"
        if (root / "design.schema.json").is_file():
            for name in ("design", "scenario", "scenario-v1", "run"):
                if not (root / f"{name}.schema.json").is_file():
                    raise FileNotFoundError(name)
            files.update({f"schemas/{p.name}": p for p in sorted(root.glob("*.schema.json"))})
            return files
    raise FileNotFoundError("schemas")


def installed_runtime() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_cache_tag": str(sys.implementation.cache_tag),
        "python_optimize": str(sys.flags.optimize),
        **{name: importlib.metadata.version(name) for name in DEPENDENCIES},
        **{f"env:{name}": os.environ.get(name, "") for name in
           ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
    }


def unavailable_identity(reason: str) -> dict[str, Any]:
    return {"key_format": KEY_FORMAT, "simulation_semantics": SIMULATION_SEMANTICS,
            "status": "unavailable", "reason": reason}


class ProcessImplementation:
    """A fail-closed snapshot; a detected change requires a new process."""

    def __init__(self, files: Callable[[], dict[str, Path]] = installed_files,
                 runtime: Callable[[], dict[str, str]] = installed_runtime):
        self._files, self._runtime = files, runtime
        self._failure: str | None = None
        try:
            self._manifest = self._read()
            self._identity = {
                "key_format": KEY_FORMAT, "simulation_semantics": SIMULATION_SEMANTICS,
                "status": "verified", "implementation_hash": _digest(self._manifest),
                "manifest": self._manifest,
            }
        except (OSError, ValueError, ImportError):
            self._failure = "implementation_unavailable"

    def _read(self) -> dict[str, Any]:
        files = self._files()
        if not files:
            raise ValueError("empty implementation inventory")
        return {
            "files": {name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                      for name, path in sorted(files.items())},
            "runtime": copy.deepcopy(self._runtime()),
        }

    def current(self) -> dict[str, Any]:
        if self._failure:
            return unavailable_identity(self._failure)
        try:
            if self._read() != self._manifest:
                self._failure = "implementation_changed_since_import"
        except (OSError, ValueError, ImportError):
            self._failure = "implementation_unavailable"
        if self._failure:
            return unavailable_identity(self._failure)
        return copy.deepcopy(self._identity)


# Imported at the very start of common.__init__, before the simulator or API
# implementation loads. Reloading a service means starting a fresh process.
PROCESS_IMPLEMENTATION = ProcessImplementation()
