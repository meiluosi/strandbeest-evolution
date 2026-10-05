"""The edit algebra (ADR-0003, E3-02/E3-03): every change to a design is a typed, reversible, logged operation.

An operation is {id, type, args, actor{kind, id}, reason, time}. `apply_op` applies one to a design document, runs the
validity guard, and returns the new design plus the inverse (a `patch` operation that turns the new design back into the
old one, so `apply + undo` is the identity by construction). `replay(base, ops)` folds a log; `History` adds undo/redo.
Humans, optimisers and agents all go through here; nothing may edit a design any other way.
Twin of packages/core/src/ops.ts; both are checked against contracts/ops/cases.json.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .guard import design_problems
from .ids import new_ulid
from .jsonpatch import apply_patch, diff

Design = dict[str, Any]
Guard = Callable[[Design], list[dict[str, str]]]
ACTOR_KINDS = ("human", "algorithm", "agent")
SYSTEM_ACTOR = {"kind": "human", "id": "unknown"}


class OpError(ValueError):
    """The operation cannot be applied to this design (unknown type, bad arguments, precondition not met)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


class GuardError(ValueError):
    """The operation would introduce errors; the design is unchanged."""

    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__("rejected by the validity guard: " + "; ".join(f"{p['code']} ({p['message']})" for p in problems))
        self.problems = problems


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_op(type: str, args: dict[str, Any], actor: dict[str, str] | None = None, reason: str = "", time: str | None = None, id: str | None = None) -> dict[str, Any]:
    return {"id": id or new_ulid(), "type": type, "args": args, "actor": actor or dict(SYSTEM_ACTOR), "reason": reason, "time": time or now_iso()}


# ------------------------------------------------------------------------------------------------ operation types
def _need(args: dict[str, Any], key: str, kinds: tuple[type, ...], what: str) -> Any:
    v = args.get(key)
    if isinstance(v, bool) or not isinstance(v, kinds):
        raise OpError("bad_args", f"'{key}' must be {what}")
    return v


def _refs(doc: Design) -> dict[str, list[str]]:
    """Where every named param is used: name -> list of places."""
    lk = doc["linkage"]
    uses: dict[str, list[str]] = {}
    for key in ("x", "y", "length"):
        r = lk["crank"][key]
        if isinstance(r, str):
            uses.setdefault(r, []).append(f"crank.{key}")
    for j in lk["joints"]:
        for k, r in enumerate(j["radii"]):
            if isinstance(r, str):
                uses.setdefault(r, []).append(f"{j['id']}.radii[{k}]")
    return uses


def _set_param(doc: Design, a: dict[str, Any]) -> None:
    name = _need(a, "name", (str,), "a string")
    value = _need(a, "value", (int, float), "a number")
    params = doc["linkage"]["params"]
    if name not in params:
        raise OpError("unknown_param", f"'{name}' is not an entry of params")
    params[name] = value


def _add_dyad(doc: Design, a: dict[str, Any]) -> None:
    lk = doc["linkage"]
    jid = _need(a, "id", (str,), "a string")
    centers = _need(a, "centers", (list,), "a list of two point ids")
    radii = _need(a, "radii", (list,), "a list of two lengths (names or numbers)")
    side = a.get("side")
    if side not in (1, -1) or isinstance(side, bool):
        raise OpError("bad_args", "'side' must be 1 or -1")
    if len(centers) != 2 or len(radii) != 2:
        raise OpError("bad_args", "'centers' and 'radii' need exactly two entries")
    new_params = a.get("params", {})
    if not isinstance(new_params, dict):
        raise OpError("bad_args", "'params' must be an object of new named lengths")
    for name, v in new_params.items():
        if name in lk["params"]:
            raise OpError("param_exists", f"'{name}' already exists; use set_param to change it")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise OpError("bad_args", f"params.{name} must be a number")
    if any(j["id"] == jid for j in lk["joints"]):
        raise OpError("joint_exists", f"a joint '{jid}' already exists")
    lk["params"].update(new_params)
    lk["joints"].append({"id": jid, "centers": list(centers), "radii": list(radii), "side": side})
    if a.get("foot"):
        lk["foot"] = jid


def _remove_joint(doc: Design, a: dict[str, Any]) -> None:
    lk = doc["linkage"]
    jid = _need(a, "id", (str,), "a string")
    victim = next((j for j in lk["joints"] if j["id"] == jid), None)
    if victim is None:
        raise OpError("unknown_joint", f"no joint '{jid}'")
    users = [j["id"] for j in lk["joints"] if jid in j["centers"]]
    if users:
        raise OpError("joint_in_use", f"joint(s) {', '.join(users)} are built on '{jid}'; remove those first")
    if lk["foot"] == jid:
        new_foot = a.get("foot")
        if not isinstance(new_foot, str):
            raise OpError("foot_needed", f"'{jid}' is the foot; give the id of the new foot in 'foot'")
        if new_foot == jid or (new_foot not in ("C",) and all(j["id"] != new_foot for j in lk["joints"])):
            raise OpError("unknown_joint", f"the new foot '{new_foot}' is not a remaining joint")
        lk["foot"] = new_foot
    before = _refs(doc)
    lk["joints"] = [j for j in lk["joints"] if j["id"] != jid]
    if a.get("drop_params", True):
        still = _refs(doc)
        for r in victim["radii"]:
            if isinstance(r, str) and r in before and r not in still:
                del lk["params"][r]


def _array_legs(doc: Design, a: dict[str, Any]) -> None:
    n = _need(a, "legs", (int,), "an integer")
    if n < 1:
        raise OpError("bad_args", "'legs' must be at least 1")
    doc["walker"]["legs"] = n


def _scale(doc: Design, a: dict[str, Any]) -> None:
    f = _need(a, "factor", (int, float), "a number")
    if f <= 0:
        raise OpError("bad_args", "'factor' must be positive")
    lk = doc["linkage"]
    for k in lk["params"]:
        lk["params"][k] = lk["params"][k] * f
    for key in ("x", "y", "length"):
        if not isinstance(lk["crank"][key], str):
            lk["crank"][key] = lk["crank"][key] * f
    for j in lk["joints"]:
        j["radii"] = [r if isinstance(r, str) else r * f for r in j["radii"]]
    if a.get("keep_physical"):
        doc["walker"]["unit_m"] = doc["walker"]["unit_m"] / f


def _mirror(doc: Design, a: dict[str, Any]) -> None:
    """Reflect the leg left to right (x -> -x). The crank must turn the other way to walk forward, and every circle
    intersection swaps sides. The crank pivot's x coordinate is negated, so it must be its own named length or a number."""
    lk = doc["linkage"]
    r = lk["crank"]["x"]
    if isinstance(r, str):
        if len(_refs(doc).get(r, [])) != 1:
            raise OpError("shared_param", f"crank.x uses '{r}', which is shared with other places; give the crank pivot its own length first")
        lk["params"][r] = -lk["params"][r]
    else:
        lk["crank"]["x"] = -r
    for j in lk["joints"]:
        j["side"] = -j["side"]
    doc["walker"]["direction"] = -doc["walker"]["direction"]


def _set_material(doc: Design, a: dict[str, Any]) -> None:
    m = _need(a, "material", (str,), "a string")
    if m not in ("PLA", "PETG"):
        raise OpError("bad_args", "'material' must be PLA or PETG")
    doc["manufacturing"]["material"] = m


@dataclass(frozen=True)
class OpType:
    name: str
    apply: Callable[[Design, dict[str, Any]], None]
    doc: str


OPS: dict[str, OpType] = {
    t.name: t
    for t in [
        OpType("set_param", _set_param, "Set one named length of the linkage."),
        OpType("add_dyad", _add_dyad, "Add a joint at the intersection of two circles (optionally with new named lengths, optionally as the foot)."),
        OpType("remove_joint", _remove_joint, "Remove a joint nothing else is built on (naming a new foot if it was the foot)."),
        OpType("array_legs", _array_legs, "Set the number of legs around the axle."),
        OpType("scale", _scale, "Multiply every length of the linkage by a factor (optionally keeping the physical size by changing the unit)."),
        OpType("mirror", _mirror, "Reflect the leg left to right and reverse the crank direction."),
        OpType("set_material", _set_material, "Choose the printing material."),
    ]
}


@dataclass
class Applied:
    design: Design
    inverse: dict[str, Any]
    warnings: list[dict[str, str]] = field(default_factory=list)


def _key(p: dict[str, str]) -> tuple[str, str]:
    return (p["code"], p["path"])


def _check_envelope(op: dict[str, Any]) -> None:
    for k in ("id", "type", "args", "actor", "reason", "time"):
        if k not in op:
            raise OpError("bad_op", f"operation is missing '{k}'")
    if op["actor"].get("kind") not in ACTOR_KINDS or not isinstance(op["actor"].get("id"), str):
        raise OpError("bad_op", "actor must be {kind: human|algorithm|agent, id}")


def apply_op(design: Design, op: dict[str, Any], guards: tuple[Guard, ...] = (design_problems,)) -> Applied:
    """Apply `op` to a copy of `design`. Raises OpError (cannot apply) or GuardError (would introduce errors); the input is never changed.

    Guard rule: errors that were already there before the operation do not block it (so a broken design can be repaired
    step by step); any error that is new does."""
    _check_envelope(op)
    new = copy.deepcopy(design)
    if op["type"] == "patch":
        try:
            new = apply_patch(new, op["args"]["patch"])
        except (ValueError, KeyError, TypeError) as e:
            raise OpError("bad_patch", str(e)) from e
    else:
        t = OPS.get(op["type"])
        if t is None:
            raise OpError("unknown_type", f"unknown operation type '{op['type']}'; known: {', '.join(sorted(OPS))}, patch")
        try:
            t.apply(new, op["args"])
        except KeyError as e:
            raise OpError("bad_design", f"the design lacks {e}") from e
    before = [p for g in guards for p in g(design)] if guards else []
    after = [p for g in guards for p in g(new)] if guards else []
    known = {_key(p) for p in before if p["level"] == "error"}
    fresh = [p for p in after if p["level"] == "error" and _key(p) not in known]
    if fresh:
        raise GuardError(fresh)
    inverse = make_op("patch", {"patch": diff(new, design)}, actor=op["actor"], reason=f"undo {op['type']} {op['id']}")
    return Applied(new, inverse, [p for p in after if p["level"] == "warning"])


def replay(base: Design, ops: list[dict[str, Any]], guards: tuple[Guard, ...] = (design_problems,)) -> Design:
    d = base
    for op in ops:
        d = apply_op(d, op, guards).design
    return d


@dataclass
class _Entry:
    op: dict[str, Any]
    forward: list[dict[str, Any]]
    backward: list[dict[str, Any]]


class History:
    """A design with its log, undo and redo. The log (`ops`) is the source of truth; `design` is its fold."""

    def __init__(self, base: Design, guards: tuple[Guard, ...] = (design_problems,)) -> None:
        self.base = copy.deepcopy(base)
        self.design = copy.deepcopy(base)
        self.guards = guards
        self._done: list[_Entry] = []
        self._undone: list[_Entry] = []

    @property
    def ops(self) -> list[dict[str, Any]]:
        return [e.op for e in self._done]

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    def commit(self, op: dict[str, Any]) -> Applied:
        applied = apply_op(self.design, op, self.guards)
        self._done.append(_Entry(op, diff(self.design, applied.design), applied.inverse["args"]["patch"]))
        self._undone.clear()
        self.design = applied.design
        return applied

    def undo(self) -> dict[str, Any]:
        """Undo the last operation (restoring a previous state is always allowed); returns the operation undone."""
        if not self._done:
            raise OpError("nothing_to_undo", "the log is empty")
        e = self._done.pop()
        self.design = apply_patch(self.design, e.backward)
        self._undone.append(e)
        return e.op

    def redo(self) -> dict[str, Any]:
        if not self._undone:
            raise OpError("nothing_to_redo", "there is nothing to redo")
        e = self._undone.pop()
        self.design = apply_patch(self.design, e.forward)
        self._done.append(e)
        return e.op
