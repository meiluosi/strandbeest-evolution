"""The MuJoCo adapter: the only module of the simulator that imports the physics engine (E4-02).

Builds the MJCF with `builder` (one hinge tree per leg plus loop-closure equalities, see builder.py), turns the neutral
`TerrainPlan` into geometry and options, and implements `PhysicsBackend` on top of MjModel/MjData."""

from __future__ import annotations

import copy
import math
from typing import TYPE_CHECKING, Any, Callable

import mujoco
import numpy as np

from ..backend import Box, BuildInfo, Contact, Energies, FootLoad, Forces, PowerBalance, Snapshot, TerrainPlan, Vec3
from ..builder import EntityBuilt, HerdBuilt, build_herd
from ..builder import build as build_mjcf
from ..builder import resolve_spec
from ..config import SimConfig
from ..fluids.anchor import StormAnchor, StormAnchorConfig
from ..fluids.feeler import WaterFeeler
from ..fluids.valves import BistableValve
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
        self._step_velocity: np.ndarray | None = None
        self._step_position: np.ndarray | None = None
        self._step_time = 0.0
        self._observation_view: MujocoBackend | None = None

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
            self._step_velocity = self.data.qvel.copy()
            self._step_position = self.data.qpos.copy()
            self._step_time = self.data.time
            mujoco.mj_step(self.model, self.data)

    def step_observation(self) -> MujocoBackend:
        """Read-only state at the last step's dynamics evaluation (the left endpoint).

        mj_step leaves derived quantities at t_n but integrates qpos/qvel to
        t_n+dt. Restore only those primary coordinates on a scratch copy to
        expose one coherent observation, without rerunning a servo under its
        previous control target or changing the next dynamics warm start.
        """
        if self._step_velocity is None:
            raise RuntimeError("step_observation requires a completed step")
        view = self._observation_view
        if view is None or view.model is not self.model:
            view = copy.copy(self)
            view.data = mujoco.MjData(self.model)
            view._observation_view = None
            self._observation_view = view
        view._has_damping = self._has_damping
        mujoco.mj_copyData(view.data, self.model, self.data)
        view.data.qpos[:] = self._step_position
        view.data.qvel[:] = self._step_velocity
        view.data.time = self._step_time
        return view

    def step_actuator_force(self, name: str) -> float:
        """Effective force used by implicitfast's velocity update.

        The simulator's servos have fixed gain and affine velocity bias.
        MuJoCo includes that bias derivative in the implicit update unless
        the actuator force was clamped. Position feedback remains explicit.
        """
        m, d = self.model, self.data
        a = self._id(mujoco.mjtObj.mjOBJ_ACTUATOR, name)
        force = float(d.actuator_force[a])
        if m.opt.integrator not in (mujoco.mjtIntegrator.mjINT_IMPLICIT, mujoco.mjtIntegrator.mjINT_IMPLICITFAST):
            return force
        if m.actuator_forcelimited[a] and not m.actuator_forcerange[a, 0] < force < m.actuator_forcerange[a, 1]:
            return force
        if m.actuator_gaintype[a] != mujoco.mjtGain.mjGAIN_FIXED:
            raise NotImplementedError("step work requires a fixed-gain actuator")
        if m.actuator_biastype[a] != mujoco.mjtBias.mjBIAS_AFFINE:
            return force
        start, count = int(d.moment_rowadr[a]), int(d.moment_rownnz[a])
        columns = d.moment_colind[start : start + count]
        dv = float(d.actuator_moment[start : start + count] @ (d.qvel[columns] - self._step_velocity[columns]))
        return force + float(m.actuator_biasprm[a, 2]) * dv

    def step_power_balance(self) -> PowerBalance:
        """Step work / dt, using the same forces as the velocity update.

        Constraint forces are explicit: F_n dot J_n*(v_n+v_next)/2.
        Joint damping is implicit: c*v_next dot (v_n+v_next)/2.
        This gives exact kinetic work for constant-mass linear systems; it
        does not hide residuals from geometry or position integration.
        """
        d = self.data
        midpoint = (self._step_velocity + d.qvel) * 0.5
        velocity = np.zeros(d.nefc)
        mujoco.mj_mulJacVec(self.model, d, velocity, midpoint)
        power = d.efc_force[:d.nefc] * velocity
        ne, nf, nl = d.ne, d.nf, d.nl
        damping_velocity = d.qvel
        viscous = float(np.sum(self.model.dof_damping * damping_velocity * midpoint)) if self._has_damping else 0.0
        return PowerBalance(-float(power[ne + nf + nl:].sum()), -float(power[:ne].sum()),
                            -float(power[ne:ne + nf].sum()), viscous)

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

    def clone(self) -> MujocoBackend:
        """Copy the compiled model and integration state without recompiling MJCF.

        MjModel is mutable: live parameter edits, actuator release and joint
        configuration all write to it. Each branch must own its model as well
        as its MjData so an experiment cannot change another branch's physics.
        """
        if self.model is None or self.data is None:
            raise RuntimeError("cannot clone unbuilt MujocoBackend")
        cloned = MujocoBackend()
        cloned.model = copy.copy(self.model)
        cloned.data = mujoco.MjData(cloned.model)
        cloned._plan = self._plan
        cloned._info = self._info
        cloned._foot_geoms = list(self._foot_geoms)
        cloned._reset_caches()
        # Preserve derived observations too. Restoring only integration state
        # calls mj_forward, which changes paused telemetry at the fork point.
        mujoco.mj_copyData(cloned.data, cloned.model, self.data)
        return cloned

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
        elif path in ("terrain.friction", "friction"):
            fric_val = float(value)
            for i in range(m.ngeom):
                if m.geom_bodyid[i] == 0:  # world body (ground plane)
                    m.geom_friction[i, 0] = fric_val
        else:
            raise KeyError(f"unknown parameter '{path}'; known: gravity, contact.softness, terrain.friction")

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
        return self._power_balance(None)

    def _power_balance(self, velocity: np.ndarray | None) -> PowerBalance:
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
        v = d.qvel if velocity is None else velocity
        viscous = float(np.sum(self.model.dof_damping * v * v)) if self._has_damping else 0.0
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


class _WalkerAgent:
    def __init__(self, name: str, info: EntityBuilt, model: mujoco.MjModel) -> None:
        self.name = name
        self.info = info
        self.torso_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, info.torso_body)
        self.actuator_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, info.actuator)
        self.crank_joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, info.crank_joint)
        self.qpos_idx = model.jnt_qposadr[self.crank_joint_id]

        self.valve = BistableValve()
        self.feeler = WaterFeeler(valve=self.valve, base_altitude=0.05)
        self.anchor = StormAnchor(StormAnchorConfig(theta_crit_deg=18.0, walker_mass=info.total_mass))
        self.direction = info.direction
        self.crank_target = -info.crank_q0
        self.omega = 2.0
        self.half_length = info.body_length / 2.0
        self.half_width = info.body_width / 2.0
        self.repulsion_fx = 0.0

        # Recording
        self.rec_x: list[float] = []
        self.rec_y: list[float] = []
        self.rec_z: list[float] = []
        self.rec_psi: list[float] = []
        self.rec_tilt: list[float] = []
        self.rec_dir: list[int] = []
        self.rec_vac: list[float] = []
        self.rec_imm: list[bool] = []
        self.rec_trip: list[bool] = []
        self.rec_anc_dep: list[bool] = []
        self.rec_anc_f: list[float] = []
        self.rec_rep_fx: list[float] = []
        self.rec_wind: list[float] = []

    def to_trajectory(self, t_arr: np.ndarray) -> Any:
        from ..runner import WalkerTrajectory

        return WalkerTrajectory(
            name=self.name,
            t=t_arr,
            x=np.array(self.rec_x, dtype=float),
            y=np.array(self.rec_y, dtype=float),
            z=np.array(self.rec_z, dtype=float),
            psi=np.array(self.rec_psi, dtype=float),
            tilt_deg=np.array(self.rec_tilt, dtype=float),
            direction=np.array(self.rec_dir, dtype=int),
            feeler_vacuum=np.array(self.rec_vac, dtype=float),
            feeler_immersed=np.array(self.rec_imm, dtype=bool),
            feeler_tripped=np.array(self.rec_trip, dtype=bool),
            anchor_deployed=np.array(self.rec_anc_dep, dtype=bool),
            anchor_holding_force=np.array(self.rec_anc_f, dtype=float),
            repulsion_force_x=np.array(self.rec_rep_fx, dtype=float),
        )


def run_herd_mujoco(
    sc: Any,
    specs: dict[str, Any] | None = None,
    wind_field: Any = None,
    tide_field: Any = None,
    duration: float = 3.0,
    dt: float | None = None,
    bumper_distance: float = 0.35,
    repulsion_k: float = 400.0,
    repulsion_c: float = 25.0,
    record_every: int = 2,
    frame_rate: float = 0.0,
) -> Any:
    from ..config import Scenario
    from ..fluids.tide import DynamicTideField
    from ..runner import HerdResult
    from ..winds import SpatiotemporalWindField

    doc = sc.model_dump(mode="json") if isinstance(sc, Scenario) else sc
    herd_built = build_herd(doc, specs=specs)
    model = mujoco.MjModel.from_xml_string(herd_built.xml)
    data = mujoco.MjData(model)

    timestep = model.opt.timestep if dt is None else dt
    model.opt.timestep = timestep

    if wind_field is None:
        wind_field = SpatiotemporalWindField()
    if tide_field is None:
        tide_field = DynamicTideField()

    agents = {
        name: _WalkerAgent(name, info, model)
        for name, info in herd_built.entities.items()
    }
    agent_names = list(agents.keys())

    total_steps = int(round(duration / timestep))
    rec_t: list[float] = []
    rec_water: list[float] = []
    collisions: list[dict[str, Any]] = []

    # Optional pose recording
    frame_every = (
        max(1, round(1.0 / (frame_rate * timestep))) if frame_rate > 0 else 0
    )
    f_t: list[float] = []
    f_pos: list[dict[str, list[float]]] = []
    f_quat: list[dict[str, list[float]]] = []

    for step_idx in range(total_steps):
        t = step_idx * timestep
        z_water = (
            tide_field(t)
            if callable(tide_field)
            else tide_field.water_level(t)
        )

        # Clear external applied forces
        data.xfrc_applied[:] = 0.0
        for agent in agents.values():
            agent.repulsion_fx = 0.0

        # 1. Dynamic wind & autonomous reflexes per walker
        for agent in agents.values():
            p_torso = data.xpos[agent.torso_id]
            v_torso = data.cvel[agent.torso_id][3:]

            # Evaluate local wind speed
            if hasattr(wind_field, "velocity"):
                w_speed = wind_field.velocity(t, p_torso[0], p_torso[1])
            elif callable(wind_field):
                w_speed = wind_field(t, p_torso[0], p_torso[1])
            else:
                w_speed = 6.0

            # Wind aerodynamic drag force on torso/sail
            # F_drag = 0.5 * rho * Area * Cd * (v_rel)^2
            v_rel_x = w_speed - v_torso[0]
            f_wind = 0.5 * 1.225 * 0.04 * 1.2 * v_rel_x * abs(v_rel_x)
            data.xfrc_applied[agent.torso_id, 0] += f_wind

            # Water feeler reflex: tip altitude relative to water surface
            # Jansen's feeler tip hangs near the ground, oscillating with stride
            z_tip = p_torso[2] - agent.info.hip_height + agent.feeler.tip_altitude(t)
            tripped = agent.feeler.step(
                timestep, z_water=z_water, override_tip_altitude=z_tip
            )
            if tripped:
                # Water contact triggers reverse reflex!
                agent.direction = -agent.direction

            # Storm anchor reflex: detect roll/pitch tilt from torso orientation matrix
            r_mat = data.xmat[agent.torso_id].reshape(3, 3)
            z_walker = r_mat[:, 2]  # local up vector in world frame
            tilt_rad = agent.anchor.compute_tilt_angle(z_walker)

            if agent.anchor.check_tilt_trigger(z_walker):
                agent.anchor.trigger("walker_tilt_collision")

            # Storm anchor holding mechanics
            if agent.anchor.is_firing or agent.anchor.is_deployed:
                # Accelerate anchor spike into beach sand
                agent.anchor._velocity = max(agent.anchor._velocity, 4.0)
                agent.anchor._penetration_depth = min(
                    agent.anchor.config.stroke,
                    agent.anchor._penetration_depth
                    + agent.anchor._velocity * timestep,
                )
                if agent.anchor._penetration_depth >= agent.anchor.config.stroke:
                    agent.anchor._deployed = True
                    agent.anchor._firing = False

                f_holding = agent.anchor.compute_holding_force(
                    agent.anchor.penetration_depth
                )
                f_hold_clamped = min(f_holding, 1500.0)

                # Linear holding resistance opposing horizontal slip
                v_horiz = np.array([v_torso[0], v_torso[1], 0.0])
                v_norm = np.linalg.norm(v_horiz)
                if v_norm > 1e-4:
                    data.xfrc_applied[agent.torso_id, :3] -= (
                        f_hold_clamped * (v_horiz / v_norm)
                    )

                # Angular holding moment righting the torso back to vertical [0, 0, 1]
                up_error = np.cross(z_walker, np.array([0.0, 0.0, 1.0]))
                data.xfrc_applied[agent.torso_id, 3:6] += 400.0 * up_error

        # 2. Multi-walker bumper collision & repulsion forces
        n_agents = len(agent_names)
        for i in range(n_agents):
            for j in range(i + 1, n_agents):
                nameA, nameB = agent_names[i], agent_names[j]
                agA, agB = agents[nameA], agents[nameB]
                posA = data.xpos[agA.torso_id]
                posB = data.xpos[agB.torso_id]
                dx = posB[0] - posA[0]
                dy = posB[1] - posA[1]
                d_horiz = math.sqrt(dx * dx + dy * dy)

                d_bumper = agA.half_length + agB.half_length + 0.06
                if d_horiz < d_bumper and abs(dy) < (agA.half_width + agB.half_width + 0.12):
                    compression = d_bumper - d_horiz
                    nx = dx / max(d_horiz, 1e-6)
                    ny = dy / max(d_horiz, 1e-6)

                    velA = data.cvel[agA.torso_id][3:]
                    velB = data.cvel[agB.torso_id][3:]
                    v_rel_n = (velB[0] - velA[0]) * nx + (velB[1] - velA[1]) * ny

                    f_rep_mag = max(0.0, repulsion_k * compression - repulsion_c * v_rel_n)
                    fx = f_rep_mag * nx
                    fy = f_rep_mag * ny

                    # Apply equal and opposite repulsion forces to torsos
                    data.xfrc_applied[agA.torso_id, 0] -= fx
                    data.xfrc_applied[agA.torso_id, 1] -= fy
                    data.xfrc_applied[agB.torso_id, 0] += fx
                    data.xfrc_applied[agB.torso_id, 1] += fy

                    agA.repulsion_fx -= fx
                    agB.repulsion_fx += fx

                    # Overturning pitch moment if pushed
                    tau_pitch = 0.08 * f_rep_mag * (1.0 if dx > 0 else -1.0)
                    data.xfrc_applied[agA.torso_id, 4] -= tau_pitch
                    data.xfrc_applied[agB.torso_id, 4] += tau_pitch

                    collisions.append({
                        "t": t,
                        "walkerA": nameA,
                        "walkerB": nameB,
                        "distance": d_horiz,
                        "repulsion_force": f_rep_mag,
                    })

        # 3. Actuator controls
        for agent in agents.values():
            if agent.anchor.is_deployed:
                # Locked in sand: disengage drive motor
                data.ctrl[agent.actuator_id] = agent.crank_target
            else:
                agent.crank_target += agent.direction * agent.omega * timestep
                data.ctrl[agent.actuator_id] = agent.crank_target

        # 4. MuJoCo physics step
        mujoco.mj_step(model, data)

        # 5. Telemetry sampling
        if step_idx % record_every == 0:
            rec_t.append(t)
            rec_water.append(z_water)
            for agent in agents.values():
                pos = data.xpos[agent.torso_id]
                psi = data.qpos[agent.qpos_idx] - agent.info.crank_q0
                r_mat = data.xmat[agent.torso_id].reshape(3, 3)
                tilt_deg = math.degrees(agent.anchor.compute_tilt_angle(r_mat[:, 2]))

                if hasattr(wind_field, "velocity"):
                    w_curr = wind_field.velocity(t, pos[0], pos[1])
                elif callable(wind_field):
                    w_curr = wind_field(t, pos[0], pos[1])
                else:
                    w_curr = 6.0

                agent.rec_x.append(pos[0])
                agent.rec_y.append(pos[1])
                agent.rec_z.append(pos[2])
                agent.rec_psi.append(psi)
                agent.rec_tilt.append(tilt_deg)
                agent.rec_dir.append(agent.direction)
                agent.rec_vac.append(agent.feeler.vacuum)
                agent.rec_imm.append(agent.feeler.is_immersed)
                agent.rec_trip.append(agent.feeler.trip_triggered)
                agent.rec_anc_dep.append(agent.anchor.is_deployed)
                f_hold = (
                    agent.anchor.compute_holding_force(agent.anchor.penetration_depth)
                    if (agent.anchor.is_deployed or agent.anchor.is_firing)
                    else 0.0
                )
                agent.rec_anc_f.append(f_hold)
                agent.rec_rep_fx.append(agent.repulsion_fx)
                agent.rec_wind.append(w_curr)

        if frame_every and step_idx % frame_every == 0:
            f_t.append(t)
            poses: dict[str, list[float]] = {}
            quats: dict[str, list[float]] = {}
            for agent in agents.values():
                poses[agent.name] = data.xpos[agent.torso_id].tolist()
                quats[agent.name] = data.xquat[agent.torso_id].tolist()
            f_pos.append(poses)
            f_quat.append(quats)

    t_arr = np.array(rec_t, dtype=float)
    trajectories = {name: ag.to_trajectory(t_arr) for name, ag in agents.items()}
    winds_dict = {name: np.array(ag.rec_wind, dtype=float) for name, ag in agents.items()}

    frames_dict = None
    if f_t:
        frames_dict = {
            "t": np.array(f_t, dtype=float),
            "pos": f_pos,
            "quat": f_quat,
        }

    return HerdResult(
        scenario=doc,
        t=t_arr,
        walkers=trajectories,
        water_levels=np.array(rec_water, dtype=float),
        wind_speeds=winds_dict,
        collisions=collisions,
        frames=frames_dict,
    )
