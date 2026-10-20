"""The MuJoCo adapter: the only module of the simulator that imports the physics engine (E4-02).

Builds the MJCF with `builder` (one hinge tree per leg plus loop-closure equalities, see builder.py), turns the neutral
`TerrainPlan` into geometry and options, and implements `PhysicsBackend` on top of MjModel/MjData."""

from __future__ import annotations

import math
from typing import Any

import mujoco
import numpy as np

from ..backend import Box, BuildInfo, Contact, Energies, FootLoad, Forces, PowerBalance, Snapshot, TerrainPlan, Vec3
from ..builder import build as build_mjcf
from ..builder import resolve_spec
from ..config import SimConfig
from . import backends

OBSTACLE = 'type="box" contype="1" conaffinity="2" rgba="0.62 0.58 0.5 1"'


def obstacles_xml(boxes: tuple[Box, ...]) -> str:
    return "".join(
        f'<geom name="{b.name}" {OBSTACLE} friction="{b.friction} 0.005 0.0001" '
        f'pos="{b.pos[0]} {b.pos[1]} {b.pos[2]}" size="{b.size[0]} {b.size[1]} {b.size[2]}"/>'
        for b in boxes
    )


def _rot(vec, quat):
    out = np.zeros(3)
    mujoco.mju_rotVecQuat(out, np.asarray(vec, float), np.asarray(quat, float))
    return out


@backends.register("mujoco")
class MujocoBackend:
    name = "mujoco"

    def __init__(self) -> None:
        self.model: mujoco.MjModel | None = None
        self.data: mujoco.MjData | None = None
        self._plan = TerrainPlan()
        self._info: BuildInfo | None = None
        self._foot_geoms: list[int] = []
        self._foot_index: dict[int, int] = {}
        self._id_cache: dict[tuple[Any, str], int] = {}
        self._qposadr_cache: dict[str, int] = {}
        self._dofadr_cache: dict[str, int] = {}
        self._has_damping: bool = False

    def _reset_caches(self) -> None:
        self._id_cache.clear()
        self._qposadr_cache.clear()
        self._dofadr_cache.clear()
        self._foot_index = {g: i for i, g in enumerate(self._foot_geoms)}
        self._has_damping = bool(np.any(self.model.dof_damping != 0)) if self.model is not None else False

    # ---- build ------------------------------------------------------------------------------------------------
    def build(self, cfg: SimConfig, plan: TerrainPlan) -> BuildInfo:
        spec = resolve_spec(cfg)
        built = build_mjcf(cfg, spec, obstacles=obstacles_xml(plan.obstacles))
        self.model = mujoco.MjModel.from_xml_string(built.xml)
        self.data = mujoco.MjData(self.model)
        m = self.model
        m.opt.enableflags |= mujoco.mjtEnableBit.mjENBL_ENERGY  # only adds the energy bookkeeping, never changes the dynamics
        self._plan = plan
        if plan.slope_deg:
            a = math.radians(plan.slope_deg)
            g = cfg.environment.gravity
            self.set_param("gravity", (-g * math.sin(a), 0.0, -g * math.cos(a)))  # uphill = +x
        if plan.softness is not None:
            self.set_param("contact.softness", plan.softness)
        self._foot_geoms = [g for g in range(m.ngeom) if (self._name(mujoco.mjtObj.mjOBJ_GEOM, g)).startswith("foot_")]
        self._reset_caches()
        mujoco.mj_forward(m, self.data)
        self._info = BuildInfo(
            n_legs=built.n_legs,
            crank_joint=built.crank_joint,
            crank_q0=built.crank_q0,
            actuator=built.actuator,
            hip_height=built.hip_height,
            bar_mass_total=built.bar_mass_total,
            body_names=tuple(self._name(mujoco.mjtObj.mjOBJ_BODY, i) for i in range(1, m.nbody)),
            foot_names=tuple(self._name(mujoco.mjtObj.mjOBJ_GEOM, g) for g in self._foot_geoms),
        )
        return self._info

    def build_reference(self, kind: str, **params: float) -> None:
        if kind == "pendulum":
            length, angle, g = float(params.get("length", 1.0)), float(params.get("angle", 0.05)), float(params.get("gravity", 9.81))
            xml = f"""<mujoco><compiler angle="radian"/><option timestep="{params.get('timestep', 0.0005)}" integrator="implicitfast" gravity="0 0 {-g}"/>
<worldbody><body name="bob"><joint name="hinge" type="hinge" axis="0 1 0" damping="0"/>
<inertial pos="0 0 -{length}" mass="1" diaginertia="1e-9 1e-9 1e-9"/>
<geom type="sphere" size="0.01" pos="0 0 -{length}" contype="0" conaffinity="0" mass="0"/></body></worldbody></mujoco>"""
            self._load_reference(xml)
            self.data.qpos[0] = angle
        elif kind == "block":
            mass, mu = float(params.get("mass", 1.0)), float(params.get("friction", 0.2))
            xml = f"""<mujoco><compiler angle="radian"/><option timestep="{params.get('timestep', 0.0005)}" integrator="implicitfast" cone="elliptic" impratio="10"/>
<worldbody><geom name="ground" type="plane" size="50 50 0.1" friction="{mu} 0.005 0.0001" contype="1" conaffinity="2"/>
<body name="block" pos="0 0 0.05"><joint name="slide_x" type="slide" axis="1 0 0"/><joint name="slide_z" type="slide" axis="0 0 1"/>
<geom type="box" size="0.05 0.05 0.05" mass="{mass}" friction="{mu} 0.005 0.0001" contype="2" conaffinity="1"/></body></worldbody></mujoco>"""
            self._load_reference(xml)
        else:
            raise KeyError(f"unknown reference system '{kind}'; known: pendulum, block")
        mujoco.mj_forward(self.model, self.data)

    def _load_reference(self, xml: str) -> None:
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        self.model.opt.enableflags |= mujoco.mjtEnableBit.mjENBL_ENERGY
        self._plan = TerrainPlan()
        self._foot_geoms = []
        self._reset_caches()

    def _name(self, kind: Any, i: int) -> str:
        return mujoco.mj_id2name(self.model, kind, i) or ""

    def _id(self, kind: Any, name: str) -> int:
        key = (kind, name)
        cached = self._id_cache.get(key)
        if cached is not None:
            return cached
        i = mujoco.mj_name2id(self.model, kind, name)
        if i < 0:
            raise KeyError(f"no {kind.name} named '{name}'")
        self._id_cache[key] = i
        return i

    def _qposadr(self, name: str) -> int:
        adr = self._qposadr_cache.get(name)
        if adr is None:
            adr = int(self.model.jnt_qposadr[self._id(mujoco.mjtObj.mjOBJ_JOINT, name)])
            self._qposadr_cache[name] = adr
        return adr

    def _dofadr(self, name: str) -> int:
        adr = self._dofadr_cache.get(name)
        if adr is None:
            adr = int(self.model.jnt_dofadr[self._id(mujoco.mjtObj.mjOBJ_JOINT, name)])
            self._dofadr_cache[name] = adr
        return adr

    # ---- stepping and state -----------------------------------------------------------------------------------
    @property
    def timestep(self) -> float:
        return float(self.model.opt.timestep)

    @property
    def time(self) -> float:
        return float(self.data.time)

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            mujoco.mj_step(self.model, self.data)

    _STATE = mujoco.mjtState.mjSTATE_INTEGRATION

    def snapshot(self) -> Snapshot:
        buf = np.zeros(mujoco.mj_stateSize(self.model, self._STATE))
        mujoco.mj_getState(self.model, self.data, buf, self._STATE)
        return Snapshot(self.name, buf)

    def restore(self, snap: Snapshot) -> None:
        if snap.backend != self.name:
            raise ValueError(f"a {snap.backend} snapshot cannot be restored into {self.name}")
        mujoco.mj_setState(self.model, self.data, snap.payload, self._STATE)
        mujoco.mj_forward(self.model, self.data)

    def set_param(self, path: str, value: Any) -> None:
        m = self.model
        if path == "gravity":
            m.opt.gravity[:] = value
        elif path == "contact.softness":
            stiffness, damping = value
            # for two geoms with direct solref MuJoCo uses the stiffer one: soften the terrain geoms (world body) and the feet
            for i in range(m.ngeom):
                if m.geom_bodyid[i] == 0 or m.geom_contype[i] == 2:
                    m.geom_solref[i] = (-float(stiffness), -float(damping))
        else:
            raise KeyError(f"unknown parameter '{path}'; known: gravity, contact.softness")

    # ---- observation ------------------------------------------------------------------------------------------
    def contacts(self) -> list[Contact]:
        m, d = self.model, self.data
        out = []
        f6 = np.zeros(6)
        for i in range(d.ncon):
            c = d.contact[i]
            mujoco.mj_contactForce(m, d, i, f6)
            frame = np.asarray(c.frame).reshape(3, 3)  # rows: normal, tangent 1, tangent 2
            force = frame.T @ f6[:3]
            out.append(
                Contact(
                    self._name(mujoco.mjtObj.mjOBJ_GEOM, int(c.geom1)),
                    self._name(mujoco.mjtObj.mjOBJ_GEOM, int(c.geom2)),
                    self._name(mujoco.mjtObj.mjOBJ_BODY, int(m.geom_bodyid[c.geom1])),
                    self._name(mujoco.mjtObj.mjOBJ_BODY, int(m.geom_bodyid[c.geom2])),
                    tuple(float(x) for x in c.pos),
                    tuple(float(x) for x in frame[0]),
                    tuple(float(x) for x in force),
                    float(-c.dist),
                )
            )
        return out

    def loop_residual(self) -> float:
        d = self.data
        return float(np.abs(d.efc_pos[: d.ne]).max()) if d.ne else 0.0

    def forces(self) -> Forces:
        m, d = self.model, self.data
        net = np.zeros(3)
        f6 = np.zeros(6)
        for i in range(d.ncon):
            mujoco.mj_contactForce(m, d, i, f6)
            net += np.asarray(d.contact[i].frame).reshape(3, 3).T @ f6[:3]
        viol = self.loop_residual()
        acts = {self._name(mujoco.mjtObj.mjOBJ_ACTUATOR, a): float(d.actuator_force[a]) for a in range(m.nu)}
        return Forces(acts, (float(net[0]), float(net[1]), float(net[2])), viol)

    def energies(self) -> Energies:
        return Energies(kinetic=float(self.data.energy[1]), potential=float(self.data.energy[0]))

    def joint_position(self, name: str) -> float:
        return float(self.data.qpos[self._qposadr(name)])

    def joint_velocity(self, name: str) -> float:
        return float(self.data.qvel[self._dofadr(name)])

    def body_position(self, name: str) -> Vec3:
        p = self.data.xpos[self._id(mujoco.mjtObj.mjOBJ_BODY, name)]
        return (float(p[0]), float(p[1]), float(p[2]))

    def body_poses(self) -> tuple[np.ndarray, np.ndarray]:
        return self.data.xpos[1:].copy(), self.data.xquat[1:].copy()

    def foot_contacts(self) -> list[bool]:
        d = self.data
        touching = set()
        for i in range(d.ncon):
            touching.add(int(d.contact[i].geom1))
            touching.add(int(d.contact[i].geom2))
        return [g in touching for g in self._foot_geoms]

    def power_balance(self) -> PowerBalance:
        """Dissipation rates from the constraint rows: -sum(force * velocity in constraint space). A friction facet that opposes
        slip has force*velocity < 0, so the dissipation is positive; the same sum covers the normal damping of a contact."""
        d = self.data
        contact = equality = fric = 0.0
        nefc = d.nefc
        if nefc:
            p = d.efc_force[:nefc] * d.efc_vel[:nefc]
            ne, nf, nl = d.ne, d.nf, d.nl
            if ne:
                equality = -float(p[:ne].sum())
            if nf:
                fric = -float(p[ne : ne + nf].sum())
            nc = ne + nf + nl
            if nc < nefc:
                contact = -float(p[nc:nefc].sum())
        viscous = float(np.sum(self.model.dof_damping * d.qvel * d.qvel)) if self._has_damping else 0.0
        return PowerBalance(contact, equality, fric, viscous)

    def foot_loads(self) -> list[FootLoad]:
        m, d = self.model, self.data
        index = self._foot_index
        normal = [0.0] * len(index)
        force = [[0.0, 0.0, 0.0] for _ in index]
        tangent_vec = [[0.0, 0.0, 0.0] for _ in index]
        slip = [0.0] * len(index)
        f6 = np.zeros(6)
        vel = np.zeros(6)
        for i in range(d.ncon):
            c = d.contact[i]
            g1, g2 = int(c.geom1), int(c.geom2)
            foot, sign = (g2, 1.0) if g2 in index else (g1, -1.0) if g1 in index else (None, 0.0)
            if foot is None:
                continue
            mujoco.mj_contactForce(m, d, i, f6)
            fr = c.frame
            fx = sign * (f6[0] * fr[0] + f6[1] * fr[3] + f6[2] * fr[6])
            fy = sign * (f6[0] * fr[1] + f6[1] * fr[4] + f6[2] * fr[7])
            fz = sign * (f6[0] * fr[2] + f6[1] * fr[5] + f6[2] * fr[8])
            nx, ny, nz = float(fr[0]), float(fr[1]), float(fr[2])
            k = index[foot]
            fn = float(fx * nx + fy * ny + fz * nz)
            normal[k] += abs(fn)
            fk = force[k]
            fk[0] += fx
            fk[1] += fy
            fk[2] += fz
            tk = tangent_vec[k]
            tk[0] += fx - fn * nx
            tk[1] += fy - fn * ny
            tk[2] += fz - fn * nz
            mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_GEOM, foot, vel, 0)  # [rot, lin] at the geom centre, world frame
            centre = d.geom_xpos[foot]
            pos = c.pos
            rx, ry, rz = float(pos[0] - centre[0]), float(pos[1] - centre[1]), float(pos[2] - centre[2])
            wx, wy, wz = float(vel[0]), float(vel[1]), float(vel[2])
            vx = float(vel[3]) + (wy * rz - wz * ry)
            vy = float(vel[4]) + (wz * rx - wx * rz)
            vz = float(vel[5]) + (wx * ry - wy * rx)
            vn = vx * nx + vy * ny + vz * nz
            slip[k] = max(slip[k], math.hypot(vx - vn * nx, vy - vn * ny, vz - vn * nz))
        return [
            FootLoad(normal[k], math.hypot(tangent_vec[k][0], tangent_vec[k][1], tangent_vec[k][2]),
                     (float(force[k][0]), float(force[k][1]), float(force[k][2])), slip[k],
                     (float(d.geom_xpos[g][0]), float(d.geom_xpos[g][1]), float(d.geom_xpos[g][2])))
            for g, k in index.items()
        ]

    def center_of_mass(self) -> Vec3:
        c = self.data.subtree_com[0]
        return (float(c[0]), float(c[1]), float(c[2]))

    def constraint_torque(self, joint: str) -> float:
        return float(self.data.qfrc_constraint[self._dofadr(joint)])

    def max_penetration(self) -> float:
        d = self.data
        return max((-float(d.contact[i].dist) for i in range(d.ncon)), default=0.0)

    def actuator_force(self, name: str) -> float:
        return float(self.data.actuator_force[self._id(mujoco.mjtObj.mjOBJ_ACTUATOR, name)])

    def describe_scene(self) -> dict:
        """Bodies (excluding the world) with their geoms, plus static obstacles, in body-local frames, for replay."""
        model = self.model
        bodies = [self._name(mujoco.mjtObj.mjOBJ_BODY, i) for i in range(1, model.nbody)]
        geoms, obstacles = [], []
        for g in range(model.ngeom):
            gtype = int(model.geom_type[g])
            body = int(model.geom_bodyid[g])
            rgba = [round(float(x), 3) for x in model.geom_rgba[g]]
            pos, quat, size = model.geom_pos[g], model.geom_quat[g], model.geom_size[g]
            name = self._name(mujoco.mjtObj.mjOBJ_GEOM, g)
            if body == 0:
                if gtype == mujoco.mjtGeom.mjGEOM_BOX:  # obstacles on the ground
                    obstacles.append({"pos": [round(float(x), 4) for x in pos], "size": [round(float(x), 4) for x in size], "name": name})
                continue
            item = {"body": body - 1, "name": name, "rgba": rgba, "foot": name.startswith("foot_")}
            if gtype == mujoco.mjtGeom.mjGEOM_CAPSULE:
                axis = _rot([0, 0, size[1]], quat)
                item.update(type="capsule", a=[round(float(x), 5) for x in pos - axis], b=[round(float(x), 5) for x in pos + axis], radius=round(float(size[0]), 5))
            elif gtype == mujoco.mjtGeom.mjGEOM_SPHERE:
                item.update(type="sphere", pos=[round(float(x), 5) for x in pos], radius=round(float(size[0]), 5))
            elif gtype == mujoco.mjtGeom.mjGEOM_BOX:
                item.update(type="box", pos=[round(float(x), 5) for x in pos], quat=[round(float(x), 6) for x in quat], size=[round(float(x), 5) for x in size])
            else:
                continue
            geoms.append(item)
        return {"bodies": bodies, "geoms": geoms, "obstacles": obstacles, "slope_deg": self._plan.slope_deg}

    # ---- actuation --------------------------------------------------------------------------------------------
    def set_actuator_target(self, name: str, value: float) -> None:
        self.data.ctrl[self._id(mujoco.mjtObj.mjOBJ_ACTUATOR, name)] = value

    def release_actuator(self, name: str) -> None:
        aid = self._id(mujoco.mjtObj.mjOBJ_ACTUATOR, name)
        self.model.actuator_gainprm[aid, :] = 0.0
        self.model.actuator_biasprm[aid, :] = 0.0

    def apply_joint_torque(self, name: str, torque: float) -> None:
        self.data.qfrc_applied[self._dofadr(name)] = torque

    def configure_joint(self, name: str, *, armature: float, damping: float, frictionloss: float) -> None:
        dof = self._dofadr(name)
        self.model.dof_armature[dof] = armature
        self.model.dof_damping[dof] = damping
        self.model.dof_frictionloss[dof] = frictionloss
        self._has_damping = bool(np.any(self.model.dof_damping != 0))
