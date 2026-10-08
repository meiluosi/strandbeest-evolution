"""The physics backend boundary (ADR-0005, E4-02).

Everything above this line (runner, drives, terrains, metrics, the API) talks to a `PhysicsBackend`; only the adapter module
of a backend (`backends/mujoco_backend.py` for MuJoCo) imports a physics engine. A backend is built from the flat `SimConfig`
(one walker in a world) plus a backend-neutral `TerrainPlan`. Every backend must pass the contract suite in
`tests/contract/` (energy conservation, mirror symmetry, unit scaling, analytic solutions).

Names are the namespaced names of the model (joint "crank0", body "torso", ...). SI units throughout; the world frame is
x forward, y lateral, z up (docs/CONVENTIONS.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from .config import SimConfig

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class Box:
    """A static block on the ground."""

    name: str
    pos: Vec3  # centre, m
    size: Vec3  # half extents, m
    friction: float


@dataclass(frozen=True)
class TerrainPlan:
    """What a terrain asks of the world, independent of any engine."""

    obstacles: tuple[Box, ...] = ()
    slope_deg: float = 0.0  # modelled by tilting gravity (uphill = +x)
    softness: tuple[float, float] | None = None  # (stiffness 1/s^2, damping 1/s) of the terrain and foot contacts, or None for rigid


@dataclass(frozen=True)
class BuildInfo:
    n_legs: int
    crank_joint: str  # driven crank joint (leg 0)
    crank_q0: float  # its reference coordinate, rad
    actuator: str
    hip_height: float  # initial torso height, m
    bar_mass_total: float
    body_names: tuple[str, ...]  # every body except the world, in the order of `body_poses`
    foot_names: tuple[str, ...]


@dataclass(frozen=True)
class Contact:
    geom1: str
    geom2: str
    body1: str
    body2: str
    pos: Vec3  # world, m
    normal: Vec3  # world, from geom1 to geom2
    force: Vec3  # world, N, force on geom2 from geom1
    depth: float  # penetration, m (positive = overlapping)


@dataclass(frozen=True)
class Forces:
    actuators: dict[str, float]  # actuator name -> generalised force (N or N*m)
    contact_net: Vec3  # sum of all contact forces, world, N
    loop_residual: float  # largest violation of a loop-closure constraint, m


@dataclass(frozen=True)
class Energies:
    kinetic: float  # J
    potential: float  # J (gravity and springs)

    @property
    def total(self) -> float:
        return self.kinetic + self.potential


@dataclass(frozen=True)
class PowerBalance:
    """Where mechanical power goes right now, W (positive = leaving the mechanical energy)."""

    contact: float  # dissipated at the contacts (friction and normal damping)
    equality: float  # dissipated by the loop-closure constraints
    joint_friction: float  # Coulomb friction in the joints
    viscous: float  # viscous damping in the joints


@dataclass(frozen=True)
class FootLoad:
    """What the ground does to one foot (all its contacts together)."""

    normal: float  # N, magnitude of the force along the contact normal
    tangent: float  # N, magnitude of the friction force
    force: Vec3  # N, world frame, force on the foot
    slip: float  # m/s, sliding speed of the contact point over the ground (largest of the foot's contacts)
    pos: Vec3  # m, world, centre of the foot


@dataclass
class Snapshot:
    """Opaque to everyone but the backend that made it: restoring it and stepping on equals stepping on without the detour."""

    backend: str
    payload: Any = field(repr=False)


@runtime_checkable
class PhysicsBackend(Protocol):
    name: str
    timestep: float  # s
    time: float  # s simulated so far

    def build(self, cfg: SimConfig, plan: TerrainPlan) -> BuildInfo: ...
    def build_reference(self, kind: str, **params: float) -> None:
        """Build a canonical test system instead of a walker, for the contract suite:
        "pendulum" (length, angle, gravity): a point mass on a massless rod, joint "hinge", body "bob", released at `angle` rad
        from hanging straight down; "block" (mass, friction): a box on a level plane that can slide in x and z, body "block"
        (tilt the plane with set_param("gravity", ...))."""
        ...
    def step(self, n: int = 1) -> None: ...
    def snapshot(self) -> Snapshot: ...
    def restore(self, snap: Snapshot) -> None: ...
    def set_param(self, path: str, value: Any) -> None:
        """Change a parameter of the built world. Paths: "gravity" (3-vector), "contact.softness" ((stiffness, damping))."""
        ...

    # observation
    def contacts(self) -> list[Contact]: ...
    def forces(self) -> Forces: ...
    def energies(self) -> Energies: ...
    def joint_position(self, name: str) -> float: ...
    def joint_velocity(self, name: str) -> float: ...
    def body_position(self, name: str) -> Vec3: ...
    def body_poses(self) -> tuple[np.ndarray, np.ndarray]:
        """World positions (B, 3) and quaternions (B, 4, w first) of every body except the world."""
        ...

    def foot_contacts(self) -> list[bool]: ...
    def foot_loads(self) -> list[FootLoad]: ...
    def power_balance(self) -> PowerBalance: ...
    def center_of_mass(self) -> Vec3: ...
    def constraint_torque(self, joint: str) -> float:
        """Generalised force the constraints (loop closures, contacts) put on a joint, N*m: the reaction the drive carries."""
        ...

    def max_penetration(self) -> float: ...
    def actuator_force(self, name: str) -> float: ...
    def describe_scene(self) -> dict: ...

    # actuation
    def set_actuator_target(self, name: str, value: float) -> None: ...
    def release_actuator(self, name: str) -> None:
        """Switch a position actuator off (zero gain), e.g. when a sail takes over from the holding servo."""
        ...

    def apply_joint_torque(self, name: str, torque: float) -> None:
        """Generalised force on a joint for the next step(s), N*m."""
        ...

    def configure_joint(self, name: str, *, armature: float, damping: float, frictionloss: float) -> None: ...
