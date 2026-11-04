"""Tests for live interactive simulation WebSocket session (G-06)."""

import pytest
from strandbeest_common.schemas import schema_dir
import json

DESIGN = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())


@pytest.mark.parametrize(
    "param,value",
    [
        ("gravity", [0.0, 0.0, -1.62]),
        ("contact.softness", [50000.0, 300.0]),
        ("terrain.friction", 3.0),
    ],
)
def test_websocket_editing_a_fork_preserves_the_other_branch_trajectory(client, param, value):
    # An independent session provides the uninterrupted reference trajectory.
    # Drive immediately so friction changes are observable in this short run.
    init = {"cmd": "init", "design": DESIGN, "overrides": {"drive": {"ramp": 0}}}
    with client.websocket_connect("/ws/sim") as reference:
        reference.send_json(init)
        assert reference.receive_json()["event"] == "ready"
        reference.send_json({"cmd": "step", "count": 200})
        reference.receive_json()
        reference.send_json({"cmd": "step", "count": 800})
        expected = reference.receive_json()

    with client.websocket_connect("/ws/sim") as ws:
        ws.send_json(init)
        assert ws.receive_json()["event"] == "ready"
        ws.send_json({"cmd": "step", "count": 200})
        ws.receive_json()
        ws.send_json({"cmd": "fork", "fork_id": "original"})
        assert ws.receive_json()["event"] == "fork_ack"
        ws.send_json({"cmd": "fork", "fork_id": "edited", "switch": True})
        assert ws.receive_json()["event"] == "fork_ack"
        ws.send_json({"cmd": "set", "param": param, "value": value})
        assert ws.receive_json()["event"] == "set_ack"
        ws.send_json({"cmd": "step", "count": 800})
        changed = ws.receive_json()
        assert changed != expected

        ws.send_json({"cmd": "switch_fork", "fork_id": "original"})
        assert ws.receive_json()["event"] == "switched"
        ws.send_json({"cmd": "step", "count": 800})
        assert ws.receive_json() == expected


def test_interactive_websocket_session_lifecycle(client):
    with client.websocket_connect("/ws/sim") as ws:
        # 1. Initialize session
        ws.send_json({"cmd": "init", "design": DESIGN})
        resp = ws.receive_json()
        assert resp["event"] == "ready"
        assert resp["t"] == 0.0

        # 2. Step forward 20 timesteps
        ws.send_json({"cmd": "step", "count": 20})
        data = ws.receive_json()
        assert data["event"] == "telemetry"
        assert data["t"] > 0
        assert "x" in data and "torque" in data
        assert data["paused"] is False

        # 3. Dynamic parameter tweak: change wind speed on the fly (G-06 slider interaction)
        ws.send_json({"cmd": "set", "param": "wind.speed", "value": 6.5})
        set_ack = ws.receive_json()
        assert set_ack["event"] == "set_ack"
        assert set_ack["value"] == 6.5

        # Step again to confirm param is reflected
        ws.send_json({"cmd": "step", "count": 10})
        data2 = ws.receive_json()
        assert data2["wind_speed"] == 6.5

        # 4. Pause simulation
        ws.send_json({"cmd": "pause"})
        assert ws.receive_json()["event"] == "paused"

        ws.send_json({"cmd": "step", "count": 10})
        data_paused = ws.receive_json()
        assert data_paused["paused"] is True
        # Time does not advance while paused
        assert data_paused["t"] == data2["t"]

        # 5. Resume
        ws.send_json({"cmd": "resume"})
        assert ws.receive_json()["event"] == "resumed"

        # 6. Snapshot & Restore
        ws.send_json({"cmd": "snapshot"})
        snap_ack = ws.receive_json()
        assert snap_ack["event"] == "snapshot_ack"
        snap_t = snap_ack["t"]

        # Step forward
        ws.send_json({"cmd": "step", "count": 20})
        data3 = ws.receive_json()
        assert data3["t"] > snap_t

        # Restore back to snapshot
        ws.send_json({"cmd": "restore"})
        restore_ack = ws.receive_json()
        assert restore_ack["event"] == "restore_ack"
        assert restore_ack["t"] == snap_t

        # 7. Dynamic friction update (G-06 ground slider)
        ws.send_json({"cmd": "set", "param": "terrain.friction", "value": 0.45})
        fric_ack = ws.receive_json()
        assert fric_ack["event"] == "set_ack"
        assert fric_ack["param"] == "terrain.friction"
        assert fric_ack["value"] == 0.45

        # 8. Defensive error handling on invalid parameter (must not crash websocket)
        ws.send_json({"cmd": "set", "param": "invalid.param.name", "value": 123})
        err_resp = ws.receive_json()
        assert err_resp["event"] == "error"
        assert "unknown parameter" in err_resp["message"]

        # 9. Fork simulation branch (G-06 timeline branching)
        ws.send_json({"cmd": "fork", "fork_id": "branch_alt", "switch": True})
        fork_ack = ws.receive_json()
        assert fork_ack["event"] == "fork_ack"
        assert fork_ack["fork_id"] == "branch_alt"

        # Step forward on the fork
        ws.send_json({"cmd": "step", "count": 10})
        data_fork = ws.receive_json()
        assert data_fork["event"] == "telemetry"
        assert data_fork["t"] > snap_t

        # 10. Close fork explicitly
        ws.send_json({"cmd": "close_fork", "fork_id": "branch_alt"})
        close_ack = ws.receive_json()
        assert close_ack["event"] == "close_fork_ack"
        assert close_ack["fork_id"] == "branch_alt"

        # Switching to closed fork returns error
        ws.send_json({"cmd": "switch_fork", "fork_id": "branch_alt"})
        err_close = ws.receive_json()
        assert err_close["event"] == "error"
        assert "unknown fork_id" in err_close["message"]


def test_interactive_websocket_fork_lru_eviction(client):
    """Enforce MAX_FORKS = 16 limit: creating 17 forks evicts the oldest fork."""
    with client.websocket_connect("/ws/sim") as ws:
        ws.send_json({"cmd": "init", "design": DESIGN})
        assert ws.receive_json()["event"] == "ready"

        # Create 16 forks: branch_0 to branch_15
        for i in range(16):
            ws.send_json({"cmd": "fork", "fork_id": f"branch_{i}"})
            ack = ws.receive_json()
            assert ack["event"] == "fork_ack"

        # All 16 forks exist
        ws.send_json({"cmd": "switch_fork", "fork_id": "branch_0"})
        assert ws.receive_json()["event"] == "switched"

        # Create the 17th fork, which should evict branch_0 (the oldest)
        ws.send_json({"cmd": "fork", "fork_id": "branch_16"})
        assert ws.receive_json()["event"] == "fork_ack"

        # branch_0 should now be evicted
        ws.send_json({"cmd": "switch_fork", "fork_id": "branch_0"})
        evicted = ws.receive_json()
        assert evicted["event"] == "error"
        assert "unknown fork_id" in evicted["message"]

        # branch_16 and branch_1 should still exist
        ws.send_json({"cmd": "switch_fork", "fork_id": "branch_1"})
        assert ws.receive_json()["event"] == "switched"
        ws.send_json({"cmd": "switch_fork", "fork_id": "branch_16"})
        assert ws.receive_json()["event"] == "switched"


@pytest.mark.parametrize("drive_kind", ["motor", "sail"])
def test_websocket_snapshot_rewinds_live_world_edits_and_repeated_continuation(client, drive_kind):
    with client.websocket_connect("/ws/sim") as ws:
        ws.send_json({"cmd": "init", "design": DESIGN,
                      "overrides": {"drive": {"kind": drive_kind, "ramp": 0}, "wind": {"speed": 3.0}}})
        assert ws.receive_json()["event"] == "ready"
        ws.send_json({"cmd": "snapshot"})  # Sail is still held by the settling servo.
        assert ws.receive_json()["event"] == "snapshot_ack"
        ws.send_json({"cmd": "step", "count": 800})
        reference = ws.receive_json()

        for _ in range(2):
            for param, value in [("gravity", [0, 0, -1.62]), ("contact.softness", [50000, 300]),
                                 ("terrain.friction", 3.0), ("wind.speed", 12), ("wind.direction", 60), ("drive.omega", 4)]:
                ws.send_json({"cmd": "set", "param": param, "value": value})
                assert ws.receive_json()["event"] == "set_ack"
            ws.send_json({"cmd": "step", "count": 200})
            assert ws.receive_json()["wind_speed"] == 12
            ws.send_json({"cmd": "restore"})
            assert ws.receive_json() == {"event": "restore_ack", "t": 0.0}
            ws.send_json({"cmd": "step", "count": 800})
            assert ws.receive_json() == reference

