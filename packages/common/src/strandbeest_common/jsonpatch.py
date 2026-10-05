"""A small deterministic JSON diff/patch (RFC 6901 pointers, RFC 6902 add/replace/remove on objects, replace on arrays).

Used to make every edit exactly reversible: the inverse of any operation is the patch that turns the new design back
into the old one. Twin of packages/core/src/jsonpatch.ts; both are checked against contracts/ops/cases.json.
Arrays of equal length are compared element by element, any other change to an array replaces it whole, so patches never
depend on index shifting.
"""

from __future__ import annotations

import copy
from typing import Any

Json = Any


def same(a: Json, b: Json) -> bool:
    """Equality that does not confuse True with 1 (Python's == does)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return False
    return a == b  # JSON numbers: 1 and 1.0 are the same value


def pointer(*parts: str | int) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _split(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise ValueError(f"bad JSON pointer: {path!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def diff(a: Json, b: Json, path: tuple[str | int, ...] = ()) -> list[dict[str, Json]]:
    """Patch steps that turn `a` into `b`, in a fixed order (keys sorted)."""
    if same(a, b):
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        steps: list[dict[str, Json]] = []
        for k in sorted(set(a) | set(b)):
            if k not in b:
                steps.append({"op": "remove", "path": pointer(*path, k)})
            elif k not in a:
                steps.append({"op": "add", "path": pointer(*path, k), "value": copy.deepcopy(b[k])})
            else:
                steps += diff(a[k], b[k], (*path, k))
        return steps
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        steps = []
        for i, (x, y) in enumerate(zip(a, b)):
            steps += diff(x, y, (*path, i))
        return steps
    return [{"op": "replace", "path": pointer(*path), "value": copy.deepcopy(b)}]


def apply_patch(doc: Json, steps: list[dict[str, Json]]) -> Json:
    """A patched deep copy of `doc`. Raises ValueError when a step does not fit the document."""
    out = copy.deepcopy(doc)
    for s in steps:
        keys = _split(s["path"])
        if not keys:
            if s["op"] != "replace":
                raise ValueError("the root can only be replaced")
            out = copy.deepcopy(s["value"])
            continue
        parent = out
        for k in keys[:-1]:
            parent = _child(parent, k, s)
        last = keys[-1]
        if isinstance(parent, list):
            i = _index(parent, last, s)
            if s["op"] != "replace":
                raise ValueError(f"only replace is supported inside arrays: {s['path']}")
            parent[i] = copy.deepcopy(s["value"])
        elif isinstance(parent, dict):
            if s["op"] == "remove":
                if last not in parent:
                    raise ValueError(f"nothing to remove at {s['path']}")
                del parent[last]
            elif s["op"] == "replace":
                if last not in parent:
                    raise ValueError(f"nothing to replace at {s['path']}")
                parent[last] = copy.deepcopy(s["value"])
            elif s["op"] == "add":
                parent[last] = copy.deepcopy(s["value"])
            else:
                raise ValueError(f"unknown patch op {s['op']!r}")
        else:
            raise ValueError(f"cannot step into a scalar at {s['path']}")
    return out


def _index(lst: list, key: str, step: dict) -> int:
    if not key.isdigit() or int(key) >= len(lst):
        raise ValueError(f"bad array index in {step['path']}")
    return int(key)


def _child(parent: Json, key: str, step: dict) -> Json:
    if isinstance(parent, list):
        return parent[_index(parent, key, step)]
    if isinstance(parent, dict) and key in parent:
        return parent[key]
    raise ValueError(f"path does not exist: {step['path']}")
