"""Interactive simulation session supporting step, pause, live parameter edits and branching (G-06)."""

from __future__ import annotations

import copy
from typing import Any

from .config import Scenario, SimConfig
from .registry import drives, winds
from .runner import Sim, make_sim


class InteractiveSession:
    """An interactive simulation session supporting step, pause, live parameter edits, and snapshot forks (G-06)."""

    def __init__(self, sim: Sim) -> None:
        self.sim = sim
        self.be = sim.backend
        self.sc = sim.scenario
        self.info = sim.info
        self.drive = drives.get(self.sc.drive.kind)(self.sim)
        self.paused = False
        self.t = 0.0
        self.dt = self.be.timestep
        self.psi_start = self.sim.psi()

    @classmethod
    def create(cls, sc: Scenario | SimConfig, backend: str = "mujoco") -> InteractiveSession:
        sim = make_sim(sc, backend=backend)
        return cls(sim)

    def step(self, steps: int = 1) -> dict[str, Any]:
        """Advance the physics by `steps` timesteps and return the latest telemetry."""
        for _ in range(steps):
            if not self.paused:
                self.drive.control(self.sim, self.t, driving=True)
                self.be.step()
                self.t += self.dt

        torso = self.be.body_position("torso")
        loads = self.be.foot_loads()
        return {
            "t": round(self.t, 4),
            "psi": round(self.sim.psi() - self.psi_start, 4),
            "x": round(torso[0], 4),
            "z": round(torso[2], 4),
            "torque": round(self.drive.torque(self.sim), 5),
            "wind_speed": float(self.sc.wind.speed),
            "paused": self.paused,
            "foot_loads": [round(l.normal, 2) for l in loads],
        }

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def set_param(self, path: str, value: Any) -> None:
        """Dynamically update wind speed, ground friction, etc."""
        if path in ("wind.speed", "wind.direction"):
            wind = self.sc.wind.model_copy(deep=True)
            if path == "wind.speed":
                wind.speed = float(value)
            else:
                # Wind direction is the existing yaw parameter, in degrees.
                wind.params["yaw_deg"] = float(value)
            wind = type(wind).model_validate(wind.model_dump())
            field = winds.get(wind.kind)(wind)
            self.sc.wind = wind
            if hasattr(self.drive, "wind"):
                # Constant fields capture speed at construction; editing only
                # Scenario would update telemetry without changing the force.
                self.drive.wind = field
        elif path == "terrain.friction":
            self.sc.terrain.friction = float(value)
            self.be.set_param("terrain.friction", float(value))
        elif path == "drive.omega":
            self.sc.drive.omega = float(value)
        else:
            self.be.set_param(path, value)

    def snapshot(self) -> dict[str, Any]:
        """Capture an independent, reusable in-memory copy of the entire world.

        PhysicsBackend.snapshot is an integration checkpoint, whereas a live
        session also permits changing the model and scenario. Copying Sim keeps
        those together (including released actuators), without recompiling MJCF.
        These opaque checkpoints are not a portable or serialized asset format.
        """
        return {
            "snapshot_version": 2,
            "t": self.t,
            "psi_start": self.psi_start,
            "paused": self.paused,
            "sim": copy.deepcopy(self.sim),
            "drive_state": self._drive_state(),
        }

    def restore(self, snap_dict: dict[str, Any]) -> None:
        """Restore configuration, model, drive and integration state atomically.

        Clone the saved world on every restore so neither later edits nor later
        stepping change the checkpoint. Wind fields are deterministic functions
        of time and their seeded scenario: rebuild them against the restored
        configuration, rather than copying closures bound to the abandoned world.
        """
        if snap_dict.get("snapshot_version") != 2 or not isinstance(snap_dict.get("sim"), Sim):
            raise ValueError("restore requires a complete interactive snapshot (version 2)")
        t, psi_start, paused = snap_dict["t"], snap_dict["psi_start"], snap_dict["paused"]
        sim = copy.deepcopy(snap_dict["sim"])
        drive = drives.get(sim.scenario.drive.kind)(sim)
        drive.__dict__.update(copy.deepcopy(snap_dict["drive_state"]))
        self.sim = sim
        self.be = sim.backend
        self.sc = sim.scenario
        self.info = sim.info
        self.drive = drive
        self.dt = self.be.timestep
        self.t = t
        self.psi_start = psi_start
        self.paused = paused

    def _drive_state(self) -> dict[str, Any]:
        # Wind closures may hold the mutable Scenario or a lazy stochastic
        # buffer. Rebuild them from the saved configuration/seed instead.
        return copy.deepcopy({key: value for key, value in vars(self.drive).items() if key != "wind"})

    def fork(self) -> InteractiveSession:
        """Fork with independent backend and scenario state, reusing compiled models when supported."""
        if hasattr(self.be, "clone"):
            forked_be = self.be.clone()
        else:
            snap = self.snapshot()
            forked = InteractiveSession.create(copy.deepcopy(self.sc), backend=self.be.name)
            forked.restore(snap)
            return forked

        forked_sim = Sim(copy.deepcopy(self.sc), forked_be, self.info)
        forked_sess = InteractiveSession(forked_sim)
        forked_sess.t = self.t
        forked_sess.psi_start = self.psi_start
        forked_sess.paused = self.paused
        forked_sess.drive.__dict__.update(self._drive_state())
        return forked_sess
