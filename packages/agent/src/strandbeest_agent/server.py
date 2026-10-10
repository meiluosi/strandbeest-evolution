"""MCP server over stdio (A-02): JSON-RPC 2.0, newline-delimited, with initialize, ping, tools/list and tools/call.

  strandbeest-mcp --workspace ./agent-workspace [--allow read,write,budget] [--confirm] [--actor my-agent]
                  [--max-runs 20] [--max-seconds 600] [--max-ops 500]

Every tool call is checked against the session's permission levels and budget and appended to <workspace>/audit.jsonl. Errors
come back as tool results with isError and a stable code, so an agent can react to them."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from .registry import Budget, Registry, Session
from .tools import default_registry
from .workspace import ToolError, Workspace

PROTOCOL = "2024-11-05"
SERVER_INFO = {"name": "strandbeest", "version": "0.1.0"}


class Server:
    def __init__(self, workspace: Workspace, session: Session, registry: Registry | None = None) -> None:
        self.ws, self.session, self.registry = workspace, session, registry or default_registry()

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # a notification (e.g. notifications/initialized): no response
            return None
        try:
            if method == "initialize":
                result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                          "instructions": "Tools to design (edit operations with a validity guard), simulate (MuJoCo), read the glass-box layers of a run and keep lab notes. Every change is logged with your actor id and reason."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.registry.describe()}
            elif method == "tools/call":
                p = msg.get("params", {})
                try:
                    out = self.registry.call(self.ws, self.session, p.get("name", ""), p.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": json.dumps(out, default=str)}], "isError": False}
                except ToolError as e:
                    result = {"content": [{"type": "text", "text": json.dumps({"code": e.code, "message": e.message, "data": e.data}, default=str)}], "isError": True}
                except (KeyError, TypeError) as e:
                    result = {"content": [{"type": "text", "text": json.dumps({"code": "bad_args", "message": f"{type(e).__name__}: {e}"})}], "isError": True}
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
        except Exception as e:  # noqa: BLE001  a bug in a handler must not kill the server
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
                stdout.flush()
                continue
            resp = self.handle(msg)
            if resp is not None:
                stdout.write(json.dumps(resp) + "\n")
                stdout.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Strandbeest MCP server (stdio)")
    ap.add_argument("--workspace", default="agent-workspace")
    ap.add_argument("--allow", default="read,write,budget", help="comma-separated permission levels: read,write,budget,confirm")
    ap.add_argument("--confirm", action="store_true", help="a human confirms the session: 'confirm' tools may run")
    ap.add_argument("--actor", default="agent")
    ap.add_argument("--max-runs", type=int, default=20)
    ap.add_argument("--max-seconds", type=float, default=600.0)
    ap.add_argument("--max-ops", type=int, default=500)
    a = ap.parse_args(argv)
    session = Session(actor_id=a.actor, allow=frozenset(a.allow.split(",")), confirmed=a.confirm, budget=Budget(a.max_runs, a.max_seconds, a.max_ops))
    Server(Workspace(a.workspace), session).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
