"""Canonical JSON serialization and content hashing (ADR-0004, E5-01).

Provides stable, deterministic SHA-256 content hashes for assets and simulation run input keys:
  input_key = (design_hash, world_hash, backend_name_and_version, platform, seed)

Rules:
- Dictionary keys are sorted lexicographically at every nesting level.
- Floating-point numbers are normalized so `1`, `1.0`, `-0.0`, and `1.0000000000000002`
  (within IEEE-754 12-significant-digit canonical formatting) produce identical representations.
- Non-semantic display metadata (`name`, `notes`, `aliases`, `created`, `updated`, `time`) can be
  excluded when hashing a Design or Scenario for simulation equivalence, or included for full asset hashing.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform as _platform
from typing import Any

# Fields on a Design or Scenario that do not affect physical simulation or geometry (display/identity metadata)
NON_AFFECTING_KEYS = frozenset({"id", "name", "notes", "aliases", "parent", "created", "updated"})


def normalize_number(val: int | float) -> int | float:
    """Normalize numbers so 1 == 1.0 and -0.0 == 0."""
    if isinstance(val, bool):
        return val
    f = float(val)
    if not math.isfinite(f):
        raise ValueError(f"cannot canonicalize non-finite number: {val!r}")
    # Round to 12 significant digits to eliminate 1e-16 representation jitter while preserving precision
    f = float(f"{f:.12g}")
    if f == 0.0:
        return 0
    if f.is_integer() and abs(f) < (1 << 53):
        return int(f)
    return f


def canonicalize(obj: Any, *, drop_keys: frozenset[str] = frozenset()) -> Any:
    """Recursively normalize a JSON-compatible value (sorted dict keys, normalized numbers)."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, (int, float)):
        return normalize_number(obj)
    if isinstance(obj, (list, tuple)):
        return [canonicalize(x, drop_keys=drop_keys) for x in obj]
    if isinstance(obj, dict):
        return {
            str(k): canonicalize(v, drop_keys=drop_keys)
            for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))
            if str(k) not in drop_keys
        }
    raise TypeError(f"unsupported type for canonical JSON: {type(obj).__name__}")


def canonical_json(obj: Any, *, drop_keys: frozenset[str] = frozenset()) -> str:
    """Compact, deterministic JSON string."""
    return json.dumps(canonicalize(obj, drop_keys=drop_keys), separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def content_hash(obj: Any, *, semantic_only: bool = False) -> str:
    """Return `sha256:<64-hex>` of `obj`. If `semantic_only=True`, strips display/identity fields (`id`, `name`, `notes`, `aliases`, `parent`)."""
    drops = NON_AFFECTING_KEYS if semantic_only else frozenset()
    digest = hashlib.sha256(canonical_json(obj, drop_keys=drops).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def host_platform_tag() -> str:
    """Normalized OS + CPU architecture tag (e.g. 'darwin-arm64', 'linux-x86_64')."""
    sys_name = _platform.system().lower()
    mach = _platform.machine().lower()
    return f"{sys_name}-{mach}"


def run_input_key(
    design: dict[str, Any],
    world_or_scenario: dict[str, Any],
    *,
    backend: str = "mujoco",
    backend_version: str = "",
    platform_tag: str | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Build the 5-tuple input key and its combined content hash (ADR-0004, E5-01)."""
    d_hash = content_hash(design, semantic_only=True)
    w_hash = content_hash(world_or_scenario, semantic_only=True)
    be_tag = f"{backend}:{backend_version}" if backend_version else backend
    plat = platform_tag if platform_tag is not None else host_platform_tag()
    tuple_doc = {
        "design_hash": d_hash,
        "world_hash": w_hash,
        "backend": be_tag,
        "platform": plat,
        "seed": int(seed),
    }
    return {
        "key": content_hash(tuple_doc),
        **tuple_doc,
    }
