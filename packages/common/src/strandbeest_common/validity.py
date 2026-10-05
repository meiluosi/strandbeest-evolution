"""Static validity of a linkage spec (E3-01, extended by the validity guard of E3-02).

The JSON Schema says what shape a LinkageSpec has; it cannot say that a name refers to something, that a joint only
uses points solved before it, or that a bar has positive length (a named value may legitimately be zero or negative when
it is a crank-pivot coordinate). Those rules live here, twin of packages/core/src/validity.ts, and both are checked against
contracts/linkage-structure/cases.json.
"""

from __future__ import annotations

from typing import Any

GROUND, CRANK_TIP, CRANK_PIVOT = "G", "C", "P"
RESERVED = {GROUND, CRANK_TIP, CRANK_PIVOT}


def structure_errors(spec: dict[str, Any]) -> list[dict[str, str]]:
    """Every static problem of the spec as {code, path, message}, in a fixed order. Empty = structurally valid."""
    errs: list[dict[str, str]] = []

    def err(code: str, path: str, message: str) -> None:
        errs.append({"code": code, "path": path, "message": message})

    params = spec.get("params", {})

    def value(ref: Any, path: str) -> float | None:
        if isinstance(ref, bool):
            return None
        if isinstance(ref, (int, float)):
            return float(ref)
        if isinstance(ref, str):
            if ref in params:
                return float(params[ref])
            err("unknown_param", path, f"{path}: '{ref}' is not an entry of params")
        return None

    crank = spec.get("crank", {})
    value(crank.get("x"), "crank.x")
    value(crank.get("y"), "crank.y")
    length = value(crank.get("length"), "crank.length")
    if length is not None and length <= 0:
        err("non_positive_length", "crank.length", f"crank.length: the crank must have positive length, got {length}")

    solved = [GROUND, CRANK_TIP]
    ids = [j.get("id") for j in spec.get("joints", [])]
    seen: set[str] = set()
    for i, j in enumerate(spec.get("joints", [])):
        jid = j.get("id")
        base = f"joints[{i}]"
        if jid in RESERVED:
            err("reserved_id", f"{base}.id", f"{base}.id: '{jid}' is reserved (G ground, C crank tip, P crank pivot)")
        elif jid in seen:
            err("duplicate_id", f"{base}.id", f"{base}.id: '{jid}' is defined twice")
        seen.add(jid)
        centers = j.get("centers", [])
        for k, c in enumerate(centers):
            if c in solved:
                continue
            if c in ids[i + 1 :]:
                err("forward_reference", f"{base}.centers[{k}]", f"{base}.centers[{k}]: '{c}' is solved after '{jid}'; order joints so each uses earlier points")
            else:
                err("unknown_point", f"{base}.centers[{k}]", f"{base}.centers[{k}]: '{c}' is not a point of this linkage")
        if len(centers) == 2 and centers[0] == centers[1]:
            err("degenerate_centers", f"{base}.centers", f"{base}.centers: both circles are centred on '{centers[0]}'")
        for k, r in enumerate(j.get("radii", [])):
            v = value(r, f"{base}.radii[{k}]")
            if v is not None and v <= 0:
                err("non_positive_length", f"{base}.radii[{k}]", f"{base}.radii[{k}]: a bar must have positive length, got {v}")
        solved.append(jid)

    foot = spec.get("foot")
    if foot not in solved or foot in (GROUND,):
        err("unknown_foot", "foot", f"foot: '{foot}' is not a joint of this linkage")
    return errs
