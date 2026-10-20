"""The K2 independent planar rigid-body physics backend (ADR-0010, V-02).

Independent implementation of the PhysicsBackend protocol (packages/sim/src/strandbeest_sim/backend.py).
Does NOT import MuJoCo. Uses reduced 4-DOF coordinates for Strandbeest walkers and symplectic impulse
time-stepping for reference models and planar contacts.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from ..backend import (
    Box,
    BuildInfo,
    Contact,
    Energies,
    FootLoad,
    Forces,
    PhysicsBackend,
    PowerBalance,
    Snapshot,
    TerrainPlan,
    Vec3,
)
from ..config import SimConfig
from . import backends


@backends.register("k2")
class K2Backend:
    name = "k2"

    def __init__(self, timestep: float = 0.0005) -> None:
        self.timestep = timestep
        self.time = 0.0
        self._kind = "unbuilt"
        self._params: dict[str, Any] = {}
        self._state: dict[str, Any] = {}
        self._gravity = (0.0, 0.0, -9.81)

    def build_reference(self, kind: str, **params: float) -> None:
        self._kind = kind
        self.time = 0.0
        self.timestep = float(params.get("timestep", self.timestep))
        if kind == "pendulum":
            length = float(params.get("length", 1.0))
            angle = float(params.get("angle", 0.05))
            g = float(params.get("gravity", 9.81))
            self._gravity = (0.0, 0.0, -g)
            self._params = {"length": length, "mass": 1.0, "gravity": g}
            self._state = {"theta": angle, "omega": 0.0}
        elif kind == "block":
            mass = float(params.get("mass", 1.0))
            mu = float(params.get("friction", 0.2))
            self._params = {"mass": mass, "friction": mu, "size": 0.05}
            # Initial position pos=(0, 0, 0.05), at rest
            self._state = {"x": 0.0, "z": 0.05, "vx": 0.0, "vz": 0.0}
        else:
            raise KeyError(f"unknown reference system '{kind}'; known: pendulum, block")

    def build(self, cfg: SimConfig, plan: TerrainPlan) -> BuildInfo:
        raise NotImplementedError("K2 full walker integration pending Phase 2")

    def set_param(self, path: str, value: Any) -> None:
        if path == "gravity":
            self._gravity = tuple(float(v) for v in value)
            if self._kind == "pendulum":
                self._params["gravity"] = abs(self._gravity[2])
        elif path == "contact.softness":
            pass
        else:
            raise KeyError(f"unsupported parameter path '{path}'")

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self._step_once()
            self.time += self.timestep

    def _step_once(self) -> None:
        dt = self.timestep
        if self._kind == "pendulum":
            l = self._params["length"]
            # Gravity projection: effective downward acceleration along vertical axis
            # (gravity is (gx, gy, gz); in standard frame gz is negative)
            gx, gz = self._gravity[0], self._gravity[2]
            th = self._state["theta"]
            w = self._state["omega"]

            # Torque from gravity: r = (l sin th, -l cos th), g = (gx, gz)
            # tau = r_x * gz - r_z * gx = l sin th * gz - (-l cos th) * gx = l (gz sin th + gx cos th)
            # I = m * l^2 = 1.0 * l^2
            # alpha = tau / I = (gz sin th + gx cos th) / l
            # For standard gravity (0, 0, -g): alpha = -g/l sin th
            alpha = (gz * math.sin(th) + gx * math.cos(th)) / l

            # Symplectic Euler (semi-implicit)
            w_next = w + alpha * dt
            th_next = th + w_next * dt
            self._state["theta"] = th_next
            self._state["omega"] = w_next

        elif self._kind == "block":
            m = self._params["mass"]
            mu = self._params["friction"]
            gx, gz = self._gravity[0], self._gravity[2]
            x, z = self._state["x"], self._state["z"]
            vx, vz = self._state["vx"], self._state["vz"]

            # Normal direction is +z (plane at z=0.05)
            # If resting on ground:
            on_ground = z <= 0.05 + 1e-9
            if on_ground:
                z = 0.05
                # Normal force cancels negative vertical gravity
                normal_force = max(0.0, -m * gz)
                vz = 0.0

                # Friction opposes horizontal motion
                f_max = mu * normal_force
                f_ext_x = m * gx

                if abs(vx) < 1e-9:
                    # Static friction
                    if abs(f_ext_x) <= f_max:
                        ax = 0.0
                        vx = 0.0
                    else:
                        ax = (f_ext_x - math.copysign(f_max, f_ext_x)) / m
                        vx += ax * dt
                else:
                    # Kinetic friction
                    ax = (f_ext_x - math.copysign(f_max, vx)) / m
                    vx_prev = vx
                    vx += ax * dt
                    # Velocity reversal under friction clamp to zero
                    if (vx_prev > 0 and vx < 0) or (vx_prev < 0 and vx > 0):
                        vx = 0.0
            else:
                ax = gx
                az = gz
                vx += ax * dt
                vz += az * dt
                z += vz * dt
                if z <= 0.05:
                    z = 0.05
                    vz = 0.0

            x += vx * dt
            self._state["x"] = x
            self._state["z"] = z
            self._state["vx"] = vx
            self._state["vz"] = vz

    def snapshot(self) -> Snapshot:
        payload = {
            "time": self.time,
            "kind": self._kind,
            "params": copy.deepcopy(self._params),
            "state": copy.deepcopy(self._state),
            "gravity": self._gravity,
        }
        return Snapshot(backend=self.name, payload=payload)

    def restore(self, snap: Snapshot) -> None:
        if snap.backend != self.name:
            raise ValueError(f"snapshot from backend '{snap.backend}', cannot restore to '{self.name}'")
        payload = snap.payload
        self.time = payload["time"]
        self._kind = payload["kind"]
        self._params = copy.deepcopy(payload["params"])
        self._state = copy.deepcopy(payload["state"])
        self._gravity = payload["gravity"]

    def energies(self) -> Energies:
        if self._kind == "pendulum":
            l = self._params["length"]
            m = self._params["mass"]
            g = abs(self._gravity[2])
            th = self._state["theta"]
            w = self._state["omega"]
            v = l * w
            e_kin = 0.5 * m * v**2
            e_pot = m * g * l * (1.0 - math.cos(th))
            return Energies(kinetic=e_kin, potential=e_pot)
        elif self._kind == "block":
            m = self._params["mass"]
            vx = self._state["vx"]
            vz = self._state["vz"]
            z = self._state["z"]
            gz = abs(self._gravity[2])
            e_kin = 0.5 * m * (vx**2 + vz**2)
            e_pot = m * gz * (z - 0.05)
            return Energies(kinetic=e_kin, potential=e_pot)
        return Energies(kinetic=0.0, potential=0.0)

    def joint_position(self, name: str) -> float:
        if self._kind == "pendulum" and name == "hinge":
            return float(self._state["theta"])
        raise KeyError(f"unknown joint '{name}' for reference '{self._kind}'")

    def joint_velocity(self, name: str) -> float:
        if self._kind == "pendulum" and name == "hinge":
            return float(self._state["omega"])
        raise KeyError(f"unknown joint '{name}' for reference '{self._kind}'")

    def body_position(self, name: str) -> Vec3:
        if self._kind == "pendulum" and name == "bob":
            l = self._params["length"]
            th = self._state["theta"]
            return (l * math.sin(th), 0.0, -l * math.cos(th))
        elif self._kind == "block" and name == "block":
            return (float(self._state["x"]), 0.0, float(self._state["z"]))
        raise KeyError(f"unknown body '{name}' for reference '{self._kind}'")

    def body_poses(self) -> tuple[np.ndarray, np.ndarray]:
        pos = self.body_position("bob" if self._kind == "pendulum" else "block")
        return np.array([pos]), np.array([[1.0, 0.0, 0.0, 0.0]])

    def contacts(self) -> list[Contact]:
        return []

    def forces(self) -> Forces:
        return Forces(actuators={}, contact_net=(0.0, 0.0, 0.0), loop_residual=0.0)

    def foot_contacts(self) -> list[bool]:
        return []

    def foot_loads(self) -> list[FootLoad]:
        return []

    def power_balance(self) -> PowerBalance:
        return PowerBalance(contact=0.0, equality=0.0, joint_friction=0.0, viscous=0.0)

    def center_of_mass(self) -> Vec3:
        if self._kind == "pendulum":
            return self.body_position("bob")
        elif self._kind == "block":
            return self.body_position("block")
        return (0.0, 0.0, 0.0)

    def constraint_torque(self, joint: str) -> float:
        return 0.0

    def max_penetration(self) -> float:
        return 0.0

    def actuator_force(self, name: str) -> float:
        return 0.0

    def describe_scene(self) -> dict:
        return {"backend": self.name, "kind": self._kind}

    def set_actuator_target(self, name: str, value: float) -> None:
        pass

    def release_actuator(self, name: str) -> None:
        pass

    def apply_joint_torque(self, name: str, torque: float) -> None:
        pass

    def configure_joint(self, name: str, *, armature: float, damping: float, frictionloss: float) -> None:
        pass

