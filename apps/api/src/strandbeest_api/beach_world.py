"""Multiplayer authoritative Digital Beach world session manager (H3-05, M8-03).

Provides:
  - Multi-client shared sandbox world with server-authoritative physics stepping.
  - Client identity, session token attribution, and entity ownership enforcement.
  - Strict input validation preventing out-of-bounds commands or unauthorized entity manipulation.
  - Resilient disconnection and reconnect token re-authentication.
  - Room concurrency budget limits and idle resource cleanup.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from strandbeest_common.ids import new_ulid
from strandbeest_sim import DynamicTideField, SpatiotemporalWindField


class BeachWorldError(Exception):
    """Base error for beach world operations."""
    code: str = "E_BEACH_WORLD_ERROR"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class RoomFullError(BeachWorldError):
    code = "E_ROOM_FULL"


class UnauthorizedEntityError(BeachWorldError):
    code = "E_UNAUTHORIZED_ENTITY"


class InvalidTokenError(BeachWorldError):
    code = "E_INVALID_TOKEN"


class InvalidInputError(BeachWorldError):
    code = "E_INVALID_INPUT"


@dataclass
class ClientSession:
    client_id: str
    token: str
    joined_at: float
    last_seen: float
    websocket: Any = None
    owned_entities: set[str] = field(default_factory=set)


@dataclass
class WorldEntity:
    entity_id: str
    owner_client_id: str
    name: str
    design: dict[str, Any]
    drive_kind: str = "motor"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.16
    vx: float = 0.0
    vy: float = 0.0
    heading: float = 0.0
    crank_angle: float = 0.0
    crank_omega: float = 2.0
    direction: int = 1
    body_length: float = 0.28
    body_width: float = 0.18
    stride_speed: float = 0.18
    feeler_vacuum: float = 0.0
    feeler_immersed: bool = False
    feeler_tripped: bool = False
    anchor_deployed: bool = False
    anchor_penetration: float = 0.0
    anchor_holding_force: float = 0.0
    repulsion_force: float = 0.0
    tilt_deg: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "owner": self.owner_client_id,
            "name": self.name,
            "drive_kind": self.drive_kind,
            "x": round(self.x, 5),
            "y": round(self.y, 5),
            "z": round(self.z, 5),
            "vx": round(self.vx, 4),
            "vy": round(self.vy, 4),
            "heading": round(self.heading, 4),
            "crank_angle": round(self.crank_angle, 4),
            "direction": self.direction,
            "feeler_vacuum": round(self.feeler_vacuum, 1),
            "feeler_immersed": self.feeler_immersed,
            "feeler_tripped": self.feeler_tripped,
            "anchor_deployed": self.anchor_deployed,
            "anchor_holding_force": round(self.anchor_holding_force, 1),
            "repulsion_force": round(self.repulsion_force, 1),
            "tilt_deg": round(self.tilt_deg, 2),
        }


def _dune_height(x: float, y: float) -> float:
    sea_slope = 0.045 * (x + 8.0)
    dune1 = 0.28 * math.sin(0.16 * x) * math.cos(0.12 * y)
    dune2 = 0.12 * math.sin(0.35 * x + 0.6) * math.sin(0.22 * y)
    ridge = 0.18 / (1.0 + math.exp(-0.25 * (x - 1.0)))
    return sea_slope + dune1 + dune2 + ridge


class BeachWorldRoom:
    """An authoritative multi-user beach world simulation room."""

    def __init__(
        self,
        world_id: str,
        max_clients: int = 8,
        max_entities: int = 32,
        dt: float = 0.05,
    ) -> None:
        self.world_id = world_id
        self.max_clients = max_clients
        self.max_entities = max_entities
        self.dt = dt

        self.clients: dict[str, ClientSession] = {}  # client_id -> ClientSession
        self.tokens: dict[str, str] = {}  # token -> client_id
        self.entities: dict[str, WorldEntity] = {}  # entity_id -> WorldEntity

        self.wind = SpatiotemporalWindField(v0=6.0, amplitude=2.0, omega=1.0, kx=0.5)
        self.tide = DynamicTideField(z0=0.05, h_tide=0.18, omega_tide=0.6)
        self.time: float = 0.0
        self.created_at: float = time.time()
        self.last_activity: float = time.time()

    @property
    def active_client_count(self) -> int:
        return sum(1 for c in self.clients.values() if c.websocket is not None)

    def join(self, client_id: str | None = None, websocket: Any = None) -> tuple[ClientSession, dict[str, Any]]:
        self.last_activity = time.time()
        cid = client_id or f"client_{new_ulid()}"

        # Prevent session hijacking: joining as an existing client requires reconnecting with token
        if cid in self.clients:
            raise BeachWorldError(
                f"Client ID '{cid}' is already in use; use reconnect with token",
                code="E_CLIENT_EXISTS",
            )

        # Check concurrency budget
        if self.active_client_count >= self.max_clients:
            raise RoomFullError(f"Room '{self.world_id}' is full (capacity {self.max_clients})")

        token = f"tok_{new_ulid()}"
        session = ClientSession(
            client_id=cid,
            token=token,
            joined_at=time.time(),
            last_seen=time.time(),
            websocket=websocket,
        )
        self.clients[cid] = session
        self.tokens[token] = cid
        return session, self.get_snapshot()

    def reconnect(self, token: str, websocket: Any = None) -> tuple[ClientSession, dict[str, Any]]:
        self.last_activity = time.time()
        cid = self.tokens.get(token)
        if not cid or cid not in self.clients:
            raise InvalidTokenError("Invalid or expired session token")

        session = self.clients[cid]
        session.websocket = websocket
        session.last_seen = time.time()
        return session, self.get_snapshot()

    def disconnect(self, client_id: str) -> None:
        if client_id in self.clients:
            self.clients[client_id].websocket = None
            self.last_activity = time.time()

    def spawn(
        self,
        token: str,
        design: dict[str, Any],
        name: str | None = None,
        x: float | None = None,
        y: float | None = None,
        heading: float = 0.0,
        direction: int = 1,
    ) -> WorldEntity:
        self.last_activity = time.time()
        cid = self.tokens.get(token)
        if not cid:
            raise InvalidTokenError("Unauthorized: invalid session token")

        # Check entity capacity
        if len(self.entities) >= self.max_entities:
            raise BeachWorldError(
                f"Room '{self.world_id}' has reached maximum entity limit ({self.max_entities})",
                code="E_ROOM_ENTITY_LIMIT",
            )

        session = self.clients[cid]
        entity_id = f"ent_{new_ulid()}"
        pos_x = float(x if x is not None else 0.0)
        pos_y = float(y if y is not None else 0.0)
        try:
            head_val = float(heading)
        except (ValueError, TypeError) as exc:
            raise InvalidInputError(f"Heading must be a valid number: {exc}")

        if not (math.isfinite(pos_x) and math.isfinite(pos_y) and math.isfinite(head_val)):
            raise InvalidInputError("Coordinates x, y and heading must be finite real numbers")

        # Determine drive kind from design
        drive_kind = "motor"
        if isinstance(design, dict):
            comp = design.get("components", {})
            d = comp.get("drive", {}) if isinstance(comp, dict) else {}
            if d.get("kind") == "sail" or design.get("drive", {}).get("kind") == "sail":
                drive_kind = "sail"

        ent = WorldEntity(
            entity_id=entity_id,
            owner_client_id=cid,
            name=name or f"Walker_{entity_id[:6]}",
            design=design,
            drive_kind=drive_kind,
            x=pos_x,
            y=pos_y,
            z=_dune_height(pos_x, pos_y) + 0.16,
            heading=head_val,
            direction=1 if direction >= 0 else -1,
        )
        self.entities[entity_id] = ent
        session.owned_entities.add(entity_id)
        return ent

    def command(
        self,
        token: str,
        entity_id: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.last_activity = time.time()
        cid = self.tokens.get(token)
        if not cid:
            raise InvalidTokenError("Unauthorized: invalid session token")

        ent = self.entities.get(entity_id)
        if not ent:
            raise BeachWorldError(f"Entity '{entity_id}' not found", code="E_ENTITY_NOT_FOUND")

        # Authority check: enforce strict ownership
        if ent.owner_client_id != cid:
            raise UnauthorizedEntityError(
                f"Client '{cid}' is not authorized to command entity '{entity_id}' owned by '{ent.owner_client_id}'"
            )

        params = params or {}
        if action == "steer":
            if "direction" in params:
                try:
                    d = int(params["direction"])
                    if d not in (-1, 1):
                        raise InvalidInputError("Direction must be 1 (forward) or -1 (reverse)")
                    ent.direction = d
                except (ValueError, TypeError) as exc:
                    raise InvalidInputError(f"Invalid direction: {exc}")
            if "heading" in params:
                try:
                    h = float(params["heading"])
                    if not math.isfinite(h):
                        raise InvalidInputError("Heading must be a finite number")
                    ent.heading = h
                except (ValueError, TypeError) as exc:
                    raise InvalidInputError(f"Invalid heading: {exc}")
        elif action == "anchor":
            deploy = bool(params.get("deployed", True))
            ent.anchor_deployed = deploy
            if not deploy:
                ent.anchor_penetration = 0.0
                ent.anchor_holding_force = 0.0
        elif action == "reverse":
            ent.direction = -ent.direction
        else:
            raise InvalidInputError(f"Unsupported action '{action}'")

        return {"event": "command_ack", "entity_id": entity_id, "action": action}

    def step(self, count: int = 1) -> dict[str, Any]:
        self.last_activity = time.time()
        for _ in range(count):
            self._step_once()
        return self.get_snapshot()

    def _step_once(self) -> None:
        dt = self.dt
        self.time += dt
        z_water = self.tide.water_level(self.time)

        # 1. Kinematics, wind aerodynamic force, and reflexes per walker
        for ent in self.entities.values():
            w_speed = self.wind.velocity(self.time, ent.x, ent.y)
            ground_z = _dune_height(ent.x, ent.y)
            ent.z = ground_z + 0.16

            # Feeler water detection reflex
            feeler_tip_z = ground_z + 0.05 + 0.035 * math.sin(2.0 * ent.crank_angle)
            ent.feeler_immersed = feeler_tip_z <= z_water

            if ent.feeler_immersed:
                ent.feeler_vacuum = min(60000.0, ent.feeler_vacuum + 90000.0 * dt)
                if ent.feeler_vacuum >= 25000.0 and not ent.feeler_tripped:
                    ent.feeler_tripped = True
                    ent.direction = -ent.direction  # Reverse away from rising water
            else:
                ent.feeler_vacuum = max(0.0, ent.feeler_vacuum - 40000.0 * dt)
                if ent.feeler_vacuum < 5000.0:
                    ent.feeler_tripped = False

            # Storm anchor holding mechanics
            if ent.anchor_deployed:
                ent.anchor_penetration = min(0.15, ent.anchor_penetration + 3.0 * dt)
                ent.anchor_holding_force = 1500.0 * (ent.anchor_penetration / 0.15)
                ent.crank_omega = 0.0
                ent.vx = 0.0
                ent.vy = 0.0
            else:
                ent.anchor_holding_force = 0.0
                # Wind relative drive
                cos_h = math.cos(ent.heading)
                sin_h = math.sin(ent.heading)
                wind_eff = w_speed * cos_h

                if ent.drive_kind == "sail":
                    # Wind-driven sail walker: strictly zero speed when wind_eff <= 0 (no self driving in zero wind)
                    if wind_eff <= 0.0:
                        speed_ratio = 0.0
                    else:
                        speed_ratio = min(3.0, 0.16 * wind_eff)
                else:
                    speed_ratio = max(0.2, 1.0 + 0.06 * wind_eff)

                ent.crank_omega = 2.0 * speed_ratio
                ent.crank_angle += ent.direction * ent.crank_omega * dt

                forward_v = ent.stride_speed * ent.direction * (ent.crank_omega / 2.0)
                ent.vx = forward_v * cos_h
                ent.vy = forward_v * sin_h
                ent.x += ent.vx * dt
                ent.y += ent.vy * dt

        # 2. Multi-walker mutual bumper collisions
        ents = list(self.entities.values())
        for e in ents:
            e.repulsion_force = 0.0

        n = len(ents)
        for i in range(n):
            for j in range(i + 1, n):
                eA, eB = ents[i], ents[j]
                dx = eB.x - eA.x
                dy = eB.y - eA.y
                dist = math.sqrt(dx * dx + dy * dy)
                bumper_dist = (eA.body_length + eB.body_length) * 0.5 + 0.08

                if dist < bumper_dist and dist > 1e-4:
                    compression = bumper_dist - dist
                    nx = dx / dist
                    ny = dy / dist

                    rvx = eB.vx - eA.vx
                    rvy = eB.vy - eA.vy
                    v_rel = rvx * nx + rvy * ny

                    f_rep = max(0.0, 350.0 * compression - 20.0 * v_rel)
                    eA.repulsion_force = max(eA.repulsion_force, f_rep)
                    eB.repulsion_force = max(eB.repulsion_force, f_rep)

                    displace = compression * 0.5
                    eA.x -= nx * displace
                    eA.y -= ny * displace
                    eB.x += nx * displace
                    eB.y += ny * displace

    def get_snapshot(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "t": round(self.time, 4),
            "wind_speed": round(self.wind.velocity(self.time), 3),
            "water_level": round(self.tide.water_level(self.time), 4),
            "client_count": self.active_client_count,
            "entities": [e.to_dict() for e in self.entities.values()],
        }


class BeachWorldManager:
    """Room registry and concurrency manager for the Digital Beach."""

    def __init__(self, default_max_clients: int = 8, idle_timeout_sec: float = 300.0) -> None:
        self.default_max_clients = default_max_clients
        self.idle_timeout_sec = idle_timeout_sec
        self.rooms: dict[str, BeachWorldRoom] = {}

    def get_or_create_room(self, world_id: str) -> BeachWorldRoom:
        self.cleanup_idle_rooms()
        if world_id not in self.rooms:
            self.rooms[world_id] = BeachWorldRoom(
                world_id=world_id,
                max_clients=self.default_max_clients,
            )
        return self.rooms[world_id]

    def remove_room(self, world_id: str) -> None:
        self.rooms.pop(world_id, None)

    def cleanup_idle_rooms(self) -> int:
        now = time.time()
        to_remove = []
        for wid, room in self.rooms.items():
            if room.active_client_count == 0 and (now - room.last_activity) > self.idle_timeout_sec:
                to_remove.append(wid)
        for wid in to_remove:
            self.rooms.pop(wid, None)
        return len(to_remove)


beach_manager = BeachWorldManager()
