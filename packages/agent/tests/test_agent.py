"""A-01 / A-02: the tool registry is generated from the edit algebra, permissions and budgets are enforced, and an external
agent can go design -> simulate -> read events -> write a note over MCP (stdio), with everything in the audit log."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from strandbeest_agent import Budget, Session, ToolError, Workspace, default_registry, operation_tools
from strandbeest_agent.registry import Registry
from strandbeest_common.ops import OPS, OpType


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "ws")


def call(reg, ws, session, tool, **args):
    return reg.call(ws, session, tool, args)


# ---------------------------------------------------------------------------------------------------- A-01
def test_there_is_one_generated_tool_per_operation_type_with_a_valid_schema():
    reg = default_registry()
    for type_ in OPS:
        tool = reg.tool(f"design.{type_}")
        assert tool.generated and tool.level == "write"
        Draft202012Validator.check_schema(tool.input_schema)
        assert "design" in tool.input_schema["required"] and "reason" in tool.input_schema["properties"]
    assert not any(n.startswith("design.patch") for n in reg.names())


def test_adding_an_operation_adds_a_tool_with_no_other_change():
    before = {t.name for t in operation_tools()}
    ops = dict(OPS)
    ops["set_colour"] = OpType("set_colour", lambda doc, a: None, "Paint the walker.")
    schema = json.loads((Path(__file__).resolve().parents[3] / "schemas" / "ops.schema.json").read_text())
    schema["$defs"]["SetColourArgs"] = {"type": "object", "required": ["colour"], "properties": {"colour": {"type": "string", "x-doc": {"en": "The colour", "zh": "颜色"}}}}
    after = operation_tools(ops, schema)
    assert {t.name for t in after} - before == {"design.set_colour"}
    new = next(t for t in after if t.name == "design.set_colour")
    assert new.input_schema["properties"]["colour"]["description"] == "The colour" and "colour" in new.input_schema["required"]


def test_generated_tools_describe_arguments_in_english_without_internal_keys():
    t = default_registry().tool("design.add_dyad")
    text = json.dumps(t.input_schema)
    assert "x-doc" not in text and "x-unit" not in text and "一" not in text
    assert t.input_schema["properties"]["side"]["enum"] == [1, -1]


def test_permission_levels_budget_confirmation_and_the_audit_log(ws):
    reg = default_registry()
    did = call(reg, ws, Session(), "design.create", example="jansen-small-6leg")["design_id"]
    read_only = Session(actor_id="reader", allow=frozenset({"read"}))
    assert call(reg, ws, read_only, "design.get", design=did)["id"] == did
    with pytest.raises(ToolError) as e:
        call(reg, ws, read_only, "design.set_param", design=did, name="m", value=14.0)
    assert e.value.code == "permission_denied"
    # confirm-level tools need a human's confirmation even when the level is allowed
    allowed = Session(allow=frozenset({"read", "write", "budget", "confirm"}))
    with pytest.raises(ToolError) as e:
        call(reg, ws, allowed, "fab.export", design=did)
    assert e.value.code == "needs_confirmation"
    # budget: 0 runs means no simulation at all, and the refusal costs nothing
    broke = Session(budget=Budget(sim_runs=0))
    with pytest.raises(ToolError) as e:
        call(reg, ws, broke, "simulate.run", design=did)
    assert e.value.code == "budget_exceeded" and broke.spent_runs == 0
    opcap = Session(budget=Budget(ops=1))
    call(reg, ws, opcap, "design.set_param", design=did, name="m", value=14.0)
    with pytest.raises(ToolError) as e:
        call(reg, ws, opcap, "design.set_param", design=did, name="m", value=15.0)
    assert e.value.code == "budget_exceeded"
    log = ws.audit_log()
    assert [x["status"] for x in log if x["actor"]["id"] == "reader"] == ["ok", "error"]
    assert any(x["error"] and x["error"]["code"] == "needs_confirmation" for x in log)


def test_edits_keep_who_and_why_and_the_guard_rejects_bad_ones(ws):
    reg = default_registry()
    s = Session(actor_id="claude-test")
    did = call(reg, ws, s, "design.create", example="jansen-small-6leg", name="mine")["design_id"]
    call(reg, ws, s, "design.set_param", design="mine", name="m", value=14.0, reason="longer stride")
    h = call(reg, ws, s, "design.history", design=did)
    op = h["steps"][0][0]
    assert op["actor"] == {"kind": "agent", "id": "claude-test"} and op["reason"] == "longer stride"
    with pytest.raises(ToolError) as e:
        call(reg, ws, s, "design.set_param", design=did, name="h", value=1.0)
    assert e.value.code == "rejected_by_guard" and e.value.data[0]["code"] == "cannot_assemble"
    assert call(reg, ws, s, "design.get", design=did)["linkage"]["params"]["h"] != 1.0
    call(reg, ws, s, "design.undo", design=did)
    assert call(reg, ws, s, "design.get", design=did)["linkage"]["params"]["m"] == 15.0
    # the workspace survives a restart: the design and its log are files
    ws2 = Workspace(ws.root)
    assert default_registry().call(ws2, Session(), "design.get", {"design": "mine"})["id"] == did


# ---------------------------------------------------------------------------------------------------- A-02
class McpClient:
    def __init__(self, workspace: Path, *flags: str) -> None:
        self.p = subprocess.Popen([sys.executable, "-m", "strandbeest_agent.server", "--workspace", str(workspace), "--actor", "ext-agent", *flags],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.n = 0

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def tool(self, tool_name, **args):
        r = self.rpc("tools/call", {"name": tool_name, "arguments": args})["result"]
        return json.loads(r["content"][0]["text"]), r["isError"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=30)


@pytest.mark.slow
def test_an_external_agent_can_design_simulate_read_events_and_write_a_note_over_mcp(tmp_path):
    c = McpClient(tmp_path / "ws")
    try:
        init = c.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})["result"]
        assert init["serverInfo"]["name"] == "strandbeest" and "tools" in init["capabilities"]
        c.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        tools = c.rpc("tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        assert {"design.set_param", "simulate.run", "simulate.query", "notes.add"} <= names
        created, err = c.tool("design.create", example="jansen-small-6leg", name="agent-walker")
        assert not err
        did = created["design_id"]
        out, err = c.tool("design.set_param", design=did, name="b", value=42.0, reason="try a shorter upper link")
        assert not err and out["design_id"] == did
        bad, err = c.tool("design.set_param", design=did, name="h", value=1.0)
        assert err and bad["code"] == "rejected_by_guard"
        run, err = c.tool("simulate.run", design=did, scene="flat", revolutions=0.7)
        assert not err and run["metrics"]["stride_per_rev"] and run["diagnosis"]
        events, err = c.tool("simulate.query", run=run["run_id"], layer="events", kinds=["touchdown"])
        assert not err and events["count"] >= 3
        feet, err = c.tool("simulate.query", run=run["run_id"], layer="feet")
        assert not err and len(feet) == 6 and all(0.0 < f["stance_fraction"] < 1.0 for f in feet)
        note, err = c.tool("notes.add", text="shorter b gives a longer stride", design=did, run=run["run_id"], tags=["stride"])
        assert not err
        # overreach is refused: this session did not get the confirm level
        denied, err = c.tool("fab.export", design=did)
        assert err and denied["code"] == "permission_denied"
    finally:
        c.close()
    ws = Workspace(tmp_path / "ws")
    audit = ws.audit_log()
    assert all(a["actor"] == {"kind": "agent", "id": "ext-agent"} for a in audit)
    assert [a["tool"] for a in audit] == ["design.create", "design.set_param", "design.set_param", "simulate.run", "simulate.query", "simulate.query", "notes.add", "fab.export"]
    assert [a["status"] for a in audit] == ["ok", "ok", "error", "ok", "ok", "ok", "ok", "error"]
    assert ws.notes()[0]["actor"]["id"] == "ext-agent"
    log = json.loads((tmp_path / "ws" / "oplogs" / f"{did}.json").read_text())
    assert log["steps"][0][0]["reason"] == "try a shorter upper link" and log["steps"][0][0]["actor"]["id"] == "ext-agent"


def test_protocol_errors_do_not_kill_the_server(tmp_path):
    c = McpClient(tmp_path / "ws")
    try:
        assert c.rpc("nope")["error"]["code"] == -32601
        c.p.stdin.write("not json\n")
        c.p.stdin.flush()
        assert json.loads(c.p.stdout.readline())["error"]["code"] == -32700
        out, err = c.tool("no.such.tool")
        assert err and out["code"] == "unknown_tool"
        assert c.rpc("ping")["result"] == {}
    finally:
        c.close()
