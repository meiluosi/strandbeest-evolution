"""The tool registry (A-01): every tool an agent may call, with its input schema, permission level and cost.

Operation tools are GENERATED from the edit algebra: one tool per operation type in strandbeest_common.ops.OPS, with the input
schema taken from schemas/ops.schema.json (the same x-doc and constraints the editor's command palette uses). Add an
operation (and its args definition) and the tool list grows by one with no code here. The rest are hand-written tools for
reading designs, running simulations, reading the glass-box layers and keeping notes.

Permission levels: read (no side effects), write (changes a design or the notes), budget (costs compute, counted against the
session budget), confirm (needs the session to have been granted confirmation; used for tools that write files outside the
workspace's design store). A session says which levels it allows; a call above that is refused with `permission_denied`."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from strandbeest_common.ops import OPS, GuardError, OpError
from strandbeest_common.schemas import schema_dir

from .workspace import ToolError, Workspace

LEVELS = ("read", "write", "budget", "confirm")


@dataclass
class Budget:
    sim_runs: int = 20
    sim_seconds: float = 600.0
    ops: int = 500


@dataclass
class Session:
    actor_id: str = "agent"
    actor_kind: str = "agent"
    allow: frozenset[str] = frozenset({"read", "write", "budget"})
    confirmed: bool = False  # a human has said yes to `confirm` tools for this session
    budget: Budget = field(default_factory=Budget)
    spent_runs: int = 0
    spent_seconds: float = 0.0
    spent_ops: int = 0

    @property
    def actor(self) -> dict[str, str]:
        return {"kind": self.actor_kind, "id": self.actor_id}


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    level: str
    handler: Callable[[Workspace, Session, dict[str, Any]], Any]
    generated: bool = False

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema, "annotations": {"level": self.level, "generated": self.generated}}


def _pascal(s: str) -> str:
    return "".join(p.capitalize() for p in s.split("_"))


def _ops_schema() -> dict[str, Any]:
    return json.loads((schema_dir() / "ops.schema.json").read_text())


def _strip_for_tool(node: Any) -> Any:
    """Keep what an agent needs: types, constraints, enums, docs (English). Drop zh docs and the x- keys."""
    if isinstance(node, dict):
        out = {k: _strip_for_tool(v) for k, v in node.items() if not k.startswith("x-")}
        doc = node.get("x-doc", {}).get("en") if isinstance(node.get("x-doc"), dict) else None
        if doc and "description" not in out:
            out["description"] = doc
        if "x-unit" in node and "description" in out:
            out["description"] += f" (unit: {node['x-unit']})"
        return out
    if isinstance(node, list):
        return [_strip_for_tool(v) for v in node]
    return node


def operation_tools(ops: dict[str, Any] | None = None, schema: dict[str, Any] | None = None) -> list[Tool]:
    """One tool per operation type, generated from the algebra and the ops schema."""
    ops = ops if ops is not None else OPS
    schema = schema or _ops_schema()
    defs = schema["$defs"]
    tools = []
    for type_, t in sorted(ops.items()):
        args = defs.get(f"{_pascal(type_)}Args")
        props = _strip_for_tool(args["properties"]) if args else {}
        required = list(args.get("required", [])) if args else []
        refs_needed = _defs_used(props, defs)
        description = (args or {}).get("x-doc", {}).get("en") or ""
        input_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "design": {"type": "string", "description": "Design id or name"},
                **props,
                "reason": {"type": "string", "description": "Why you make this change; it is kept in the log for people and other agents"},
            },
            "required": ["design", *required],
            "$defs": {k: _strip_for_tool(v) for k, v in defs.items() if k in refs_needed},
        }
        if not input_schema["$defs"]:
            del input_schema["$defs"]
        tools.append(
            Tool(
                name=f"design.{type_}",
                description=t.doc if not description or description in t.doc else f"{t.doc} {description}",
                input_schema=input_schema,
                level="write",
                handler=_op_handler(type_),
                generated=True,
            )
        )
    return tools


def _defs_used(node: Any, defs: dict[str, Any], seen: set[str] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.split("/")[-1]
            if name not in seen and name in defs:
                seen.add(name)
                _defs_used(defs[name], defs, seen)
        for v in node.values():
            _defs_used(v, defs, seen)
    elif isinstance(node, list):
        for v in node:
            _defs_used(v, defs, seen)
    return seen


def _op_handler(type_: str):
    def handler(ws: Workspace, session: Session, args: dict[str, Any]) -> Any:
        args = dict(args)
        ref = args.pop("design", None)
        if ref is None:
            raise ToolError("bad_args", "'design' is required")
        reason = args.pop("reason", "")
        if session.spent_ops >= session.budget.ops:
            raise ToolError("budget_exceeded", f"operation budget of {session.budget.ops} used up")
        try:
            out = ws.apply(ref, type_, args, session.actor, reason)
        except OpError as e:
            raise ToolError(e.code, e.message) from e
        except GuardError as e:
            raise ToolError("rejected_by_guard", str(e), data=e.problems) from e
        session.spent_ops += 1
        return {"design_id": out["design_id"], "operation_id": out["operation_id"], "warnings": out["warnings"]}

    return handler


class Registry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        return [self._tools[n].describe() for n in self.names()]

    def tool(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError("unknown_tool", f"no tool '{name}'")
        return self._tools[name]

    def call(self, ws: Workspace, session: Session, name: str, args: dict[str, Any] | None = None) -> Any:
        """Check permission and budget, run the tool, audit the call. Raises ToolError."""
        args = args or {}
        started = time.time()
        status, detail = "ok", None
        try:
            tool = self.tool(name)
            if tool.level not in session.allow:
                raise ToolError("permission_denied", f"tool '{name}' needs the '{tool.level}' level; this session allows {sorted(session.allow)}")
            if tool.level == "confirm" and not session.confirmed:
                raise ToolError("needs_confirmation", f"tool '{name}' changes things outside the design store and needs a human to confirm this session")
            if tool.level == "budget":
                if session.spent_runs >= session.budget.sim_runs:
                    raise ToolError("budget_exceeded", f"simulation budget of {session.budget.sim_runs} runs used up")
                if session.spent_seconds >= session.budget.sim_seconds:
                    raise ToolError("budget_exceeded", f"compute budget of {session.budget.sim_seconds:g} s used up")
            result = tool.handler(ws, session, args)
            if tool.level == "budget":
                session.spent_runs += 1
                session.spent_seconds += time.time() - started
            return result
        except ToolError as e:
            status, detail = "error", {"code": e.code, "message": e.message}
            raise
        finally:
            ws.audit({"actor": session.actor, "tool": name, "args": _short(args), "status": status, "error": detail, "seconds": round(time.time() - started, 3)})


def _short(args: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in args.items():
        s = json.dumps(v, default=str)
        out[k] = v if len(s) < 300 else f"<{len(s)} chars>"
    return out
