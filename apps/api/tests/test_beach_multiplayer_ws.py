"""Tests for Multiplayer Digital Beach WebSocket session (H3-05, M8-03).

Acceptance criteria:
- At least two independent clients join the same shared world.
- Server maintains authoritative world state; both clients receive synchronized identical motion.
- Client identity & token attribution: entities have owners.
- Authority check: cross-user unauthorized entity commands rejected with E_UNAUTHORIZED_ENTITY.
- Input validation: invalid actions or non-finite inputs rejected.
- Disconnection & reconnection with token restores entity ownership.
- Concurrency budget & room capacity limit (E_ROOM_FULL).
- Idle room resource release.
"""

import json
import pytest
from strandbeest_common.schemas import schema_dir
from strandbeest_api.beach_world import BeachWorldRoom, beach_manager

DESIGN = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())


def test_beach_multiplayer_two_clients_join_and_sync(client):
    """Verify two independent clients join the same world and observe identical synchronized states."""
    world_id = "shared_beach_test"
    with client.websocket_connect(f"/ws/beach?world_id={world_id}") as ws_a:
        # Client A joins
        ws_a.send_json({"cmd": "join", "client_id": "client_A"})
        joined_a = ws_a.receive_json()
        assert joined_a["event"] == "joined"
        assert joined_a["client_id"] == "client_A"
        token_a = joined_a["token"]

        with client.websocket_connect(f"/ws/beach?world_id={world_id}") as ws_b:
            # Client B joins
            ws_b.send_json({"cmd": "join", "client_id": "client_B"})
            joined_b = ws_b.receive_json()
            assert joined_b["event"] == "joined"
            assert joined_b["client_id"] == "client_B"
            token_b = joined_b["token"]

            # Client A spawns walker_A
            ws_a.send_json({
                "cmd": "spawn",
                "token": token_a,
                "name": "WalkerA",
                "design": DESIGN,
                "x": 0.0,
                "y": 0.0,
                "direction": 1,
            })
            spawn_ack_a = ws_a.receive_json()
            assert spawn_ack_a["event"] == "spawned"
            ent_a_id = spawn_ack_a["entity"]["entity_id"]
            assert spawn_ack_a["entity"]["owner"] == "client_A"

            # Client B also receives spawn broadcast
            spawn_b_received = ws_b.receive_json()
            assert spawn_b_received["event"] == "spawned"
            assert spawn_b_received["entity"]["entity_id"] == ent_a_id

            # Client B spawns walker_B
            ws_b.send_json({
                "cmd": "spawn",
                "token": token_b,
                "name": "WalkerB",
                "design": DESIGN,
                "x": 2.0,
                "y": 0.5,
                "direction": -1,
            })
            spawn_ack_b = ws_b.receive_json()
            assert spawn_ack_b["event"] == "spawned"
            ent_b_id = spawn_ack_b["entity"]["entity_id"]
            assert spawn_ack_b["entity"]["owner"] == "client_B"

            # Client A receives spawn broadcast for B
            spawn_a_recv_b = ws_a.receive_json()
            assert spawn_a_recv_b["event"] == "spawned"
            assert spawn_a_recv_b["entity"]["entity_id"] == ent_b_id

            # Step simulation: Client A triggers step
            ws_a.send_json({"cmd": "step", "count": 10})

            tick_a = ws_a.receive_json()
            assert tick_a["event"] == "tick"
            snap_a = tick_a["snapshot"]
            assert snap_a["t"] > 0

            # Client B receives identical tick snapshot
            tick_b = ws_b.receive_json()
            assert tick_b["event"] == "tick"
            snap_b = tick_b["snapshot"]

            # Exact motion synchronization: both clients receive identical entity positions
            assert snap_a == snap_b
            assert len(snap_a["entities"]) == 2


def test_beach_multiplayer_authority_check_rejects_unauthorized_command(client):
    """Verify that Client A cannot steer or control Client B's entity."""
    world_id = "security_beach_test"
    with client.websocket_connect(f"/ws/beach?world_id={world_id}") as ws_a:
        ws_a.send_json({"cmd": "join", "client_id": "alice"})
        token_a = ws_a.receive_json()["token"]

        with client.websocket_connect(f"/ws/beach?world_id={world_id}") as ws_b:
            ws_b.send_json({"cmd": "join", "client_id": "bob"})
            token_b = ws_b.receive_json()["token"]

            # Bob spawns his walker
            ws_b.send_json({
                "cmd": "spawn",
                "token": token_b,
                "name": "BobsWalker",
                "design": DESIGN,
            })
            ent_b = ws_b.receive_json()["entity"]["entity_id"]
            ws_a.receive_json()  # drain broadcast

            # Alice tries to steer Bob's walker!
            ws_a.send_json({
                "cmd": "command",
                "token": token_a,
                "entity_id": ent_b,
                "action": "steer",
                "params": {"direction": -1},
            })
            err = ws_a.receive_json()
            assert err["event"] == "error"
            assert err["code"] == "E_UNAUTHORIZED_ENTITY"

            # Bob steers his own walker successfully
            ws_b.send_json({
                "cmd": "command",
                "token": token_b,
                "entity_id": ent_b,
                "action": "steer",
                "params": {"direction": -1},
            })
            ack = ws_b.receive_json()
            assert ack["event"] == "command_ack"
            assert ack["action"] == "steer"


def test_beach_multiplayer_input_validation(client):
    """Verify input validation rejects non-finite coordinates or invalid commands."""
    world_id = "val_beach_test"
    with client.websocket_connect(f"/ws/beach?world_id={world_id}") as ws:
        ws.send_json({"cmd": "join"})
        token = ws.receive_json()["token"]

        # Spawn with NaN or Inf
        ws.send_json({
            "cmd": "spawn",
            "token": token,
            "x": float("nan"),
            "y": 0.0,
            "design": DESIGN,
        })
        err = ws.receive_json()
        assert err["event"] == "error"
        assert err["code"] == "E_INVALID_INPUT"


def test_beach_multiplayer_disconnect_and_reconnect(client):
    """Verify client can disconnect and reconnect with token, retaining ownership."""
    world_id = "reconnect_beach_test"
    token = None
    ent_id = None

    # Session 1: Alice joins and spawns
    with client.websocket_connect(f"/ws/beach?world_id={world_id}") as ws1:
        ws1.send_json({"cmd": "join", "client_id": "alice"})
        resp = ws1.receive_json()
        token = resp["token"]

        ws1.send_json({"cmd": "spawn", "token": token, "name": "AliceWalker", "design": DESIGN})
        ent_id = ws1.receive_json()["entity"]["entity_id"]

        ws1.send_json({"cmd": "step", "count": 5})
        ws1.receive_json()
        # ws1 disconnects upon exiting context

    # Session 2: Alice reconnects using token
    with client.websocket_connect(f"/ws/beach?world_id={world_id}") as ws2:
        ws2.send_json({"cmd": "reconnect", "token": token})
        reconnected = ws2.receive_json()
        assert reconnected["event"] == "reconnected"
        assert reconnected["client_id"] == "alice"

        # Alice commands her persistent walker
        ws2.send_json({
            "cmd": "command",
            "token": token,
            "entity_id": ent_id,
            "action": "anchor",
            "params": {"deployed": True},
        })
        ack = ws2.receive_json()
        assert ack["event"] == "command_ack"


def test_beach_multiplayer_concurrency_budget_and_cleanup(client):
    """Verify room concurrency limit and idle room resource release."""
    room = beach_manager.get_or_create_room("capacity_test")
    room.max_clients = 2

    with client.websocket_connect("/ws/beach?world_id=capacity_test") as ws1:
        ws1.send_json({"cmd": "join", "client_id": "c1"})
        assert ws1.receive_json()["event"] == "joined"

        with client.websocket_connect("/ws/beach?world_id=capacity_test") as ws2:
            ws2.send_json({"cmd": "join", "client_id": "c2"})
            assert ws2.receive_json()["event"] == "joined"

            # 3rd client attempts to join full room
            with client.websocket_connect("/ws/beach?world_id=capacity_test") as ws3:
                ws3.send_json({"cmd": "join", "client_id": "c3"})
                err = ws3.receive_json()
                assert err["event"] == "error"
                assert err["code"] == "E_ROOM_FULL"

    # Cleanup idle rooms
    room.last_activity = 0.0  # Force idle
    cleaned = beach_manager.cleanup_idle_rooms()
    assert cleaned >= 1
