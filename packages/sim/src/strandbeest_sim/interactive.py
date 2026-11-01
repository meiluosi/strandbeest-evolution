"""Interactive simulation session supporting step, pause, live parameter edits and branching (G-06)."""

from __future__ import annotations

from typing import Any

from .config import Scenario, SimConfig
from .registry import drives
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
        if path == "wind.speed":
            self.sc.wind.speed = float(value)
        elif path == "wind.direction":
            self.sc.wind.direction = float(value)
        elif path == "terrain.friction":
            self.sc.terrain.friction = float(value)
            self.be.set_param("terrain.friction", float(value))
        elif path == "drive.omega":
            self.sc.drive.omega = float(value)
        else:
            self.be.set_param(path, value)

    def snapshot(self) -> dict[str, Any]:
        """Take a snapshot of current simulation state."""
        return {
            "t": self.t,
            "psi_start": self.psi_start,
            "paused": self.paused,
            "drive_target": getattr(self.drive, "target", 0.0),
            "drive_released": getattr(self.drive, "released", False),
            "drive_tau": getattr(self.drive, "tau", 0.0),
            "backend_snapshot": self.be.snapshot(),
        }

    def restore(self, snap_dict: dict[str, Any]) -> None:
        """Restore simulation state from a snapshot."""
        self.t = snap_dict["t"]
        self.psi_start = snap_dict["psi_start"]
        self.paused = snap_dict["paused"]
        if "drive_target" in snap_dict and hasattr(self.drive, "target"):
            self.drive.target = snap_dict["drive_target"]
        if "drive_released" in snap_dict and hasattr(self.drive, "released"):
            self.drive.released = snap_dict["drive_released"]
            if self.drive.released:
                self.be.release_actuator(self.drive.actuator)
        if "drive_tau" in snap_dict and hasattr(self.drive, "tau"):
            self.drive.tau = snap_dict["drive_tau"]
        self.be.restore(snap_dict["backend_snapshot"])

    def fork(self) -> InteractiveSession:
        """Fork the current simulation session using copy-on-write backend cloning without recompiling."""
        import copy

        if hasattr(self.be, "clone"):
            forked_be = self.be.clone()
        else:
            snap = self.snapshot()
            forked = InteractiveSession.create(self.sc, backend=self.be.name)
            forked.restore(snap)
            return forked

        forked_sim = Sim(copy.deepcopy(self.sc), forked_be, self.info)
        forked_sess = InteractiveSession(forked_sim)
        forked_sess.t = self.t
        forked_sess.psi_start = self.psi_start
        forked_sess.paused = self.paused
        if hasattr(self.drive, "target") and hasattr(forked_sess.drive, "target"):
            forked_sess.drive.target = self.drive.target
        if hasattr(self.drive, "released") and hasattr(forked_sess.drive, "released"):
            forked_sess.drive.released = self.drive.released
            if forked_sess.drive.released:
                forked_be.release_actuator(forked_sess.drive.actuator)
        if hasattr(self.drive, "tau") and hasattr(forked_sess.drive, "tau"):
            forked_sess.drive.tau = self.drive.tau
        return forked_sess
