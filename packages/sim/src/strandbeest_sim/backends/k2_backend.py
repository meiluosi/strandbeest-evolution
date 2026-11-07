"""The K2 independent planar rigid-body physics backend (ADR-0010, V-02).

Independent implementation of the PhysicsBackend protocol (packages/sim/src/strandbeest_sim/backend.py).
Does NOT import MuJoCo. Uses reduced coordinates for Strandbeest walkers and symplectic impulse
time-stepping for reference models and planar contacts.
"""

from __future__ import annotations

import copy
import math
import re
import xml.etree.ElementTree as ET
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
    StepWork,
    TerrainPlan,
    Vec3,
)
from ..builder import build as build_geometry, resolve_spec
from ..config import SimConfig
from ..linkage import solve_pose
from . import backends
from .k2_contact import ContactConvergenceError, solve_contacts
from .k2_inertia import PeriodicQuintic, WalkerInertia


@backends.register("k2")
class K2Backend:
    name = "k2"

    def __init__(self, timestep: float | None = None) -> None:
        if timestep is not None and (not math.isfinite(timestep) or timestep <= 0):
            raise ValueError("timestep must be finite and positive")
        self._requested_timestep = timestep
        self.timestep = timestep if timestep is not None else 0.0005
        self.time = 0.0
        self._kind = "unbuilt"
        self._params: dict[str, Any] = {}
        self._state: dict[str, Any] = {}
        self._gravity = (0.0, 0.0, -9.81)
        self._actuator_target = 0.0
        self._actuator_released = False
        self._applied_joint_torque = 0.0
        self._armature = 0.0
        self._damping = 0.0
        self._frictionloss = 0.0
        self._last_actuator_force = 0.0
        self._last_foot_loads: list[FootLoad] = []
        self._last_power_balance = PowerBalance(0.0, 0.0, 0.0, 0.0)
        self._last_step_work = StepWork()
        self._last_max_penetration = 0.0
        self._last_constraint_torque = 0.0
        self._contact_softness: tuple[float, float] | None = None
        self._contact_iterations = 0
        self._last_contact_iterations = 0
        self._last_contact_solution = None

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
            self._state = {"x": 0.0, "z": 0.05, "vx": 0.0, "vz": 0.0}
        else:
            raise KeyError(f"unknown reference system '{kind}'; known: pendulum, block")

    def build(self, cfg: SimConfig, plan: TerrainPlan) -> BuildInfo:
        if cfg.solver.tolerance is not None:
            raise ValueError("solver.tolerance is a MuJoCo option; K2 only accepts null")
        if self._requested_timestep is not None and self._requested_timestep != cfg.solver.timestep:
            raise ValueError("Set solver.timestep in Scenario; a K2 constructor override cannot contradict the recorded input")
        self.timestep = float(cfg.solver.timestep)
        self._contact_iterations = int(cfg.solver.iterations)
        self._last_contact_iterations = 0
        self._last_contact_solution = None
        self._kind = "walker"
        self.time = 0.0
        self._cfg = cfg
        self._plan = plan
        spec = resolve_spec(cfg)
        self._spec = spec
        # Share the model's geometry/ownership declaration, not its dynamics or
        # contact solver. In particular the sphere may belong to either bar
        # ending at F, depending on traversal order; F0 is not a safe guess.
        built = build_geometry(cfg, spec)
        tree = ET.fromstring(built.xml)
        owner = next((body for body in tree.iter('body')
                      if any(g.get('name', '').startswith('foot_bar0_') for g in body.findall('geom'))), None)
        match = re.fullmatch(r'bar0_(.+)([01])', owner.get('name', '')) if owner is not None else None
        if match is None:
            raise ValueError("K2 requires a sphere owned by a bar ending at the foot")
        foot_joint = next(j for j in spec.joints if j.id == match[1])
        self._foot_owner_start = foot_joint.centers[int(match[2])]
        self._foot_owner_suffix = match[1] + match[2]
        self._contact_softness = None
        self._solver_contact_softness = None
        self._last_foot_loads = []
        self._last_power_balance = PowerBalance(0.0, 0.0, 0.0, 0.0)
        self._last_step_work = StepWork()
        self._last_max_penetration = self._last_constraint_torque = self._last_actuator_force = 0.0
        self._armature = self._damping = self._frictionloss = 0.0

        w = cfg.walker
        u = w.unit
        n = w.legs
        self._u = u
        self._n_legs = n
        self._direction = w.direction
        self._phases = [2 * math.pi * i / n for i in range(n)]

        # Periodic C2 quintic Hermite tables: derivatives are the derivatives
        # of the interpolated positions, including the wrap at 2*pi. The owner
        # vector supplies the sphere's angular velocity without atan2 jumps.
        N_TABLE = 2880
        thetas = np.linspace(0, 2 * math.pi, N_TABLE, endpoint=False)
        poses = [solve_pose(spec, th) for th in thetas]
        if any(p is None for p in poses):
            raise ValueError("linkage cannot assemble over the K2 trajectory table")
        feet = np.array([p[spec.foot] for p in poses])*u
        starts = np.array([p[self._foot_owner_start] for p in poses])*u
        self._foot_table = np.column_stack((feet, feet-starts))
        self._table_step = math.tau/N_TABLE
        self._foot_coefficients = PeriodicQuintic(self._foot_table).coefficients
        self._N_TABLE = N_TABLE

        hip_h = built.hip_height
        self._hip_height = hip_h

        self._inertia = WalkerInertia(spec, cfg, built.xml, poses)
        self._mass_cache = None
        self._m_total = self._inertia.mass  # includes the explicitly declared sphere masses
        self._torso_mass = self._inertia.torso_mass
        self._bar_mass_total = built.bar_mass_total
        self._pitch_locked = getattr(w, "pitch", "free") == "locked"

        # State: X, Z, Phi, psi
        self._q = np.array([0.0, hip_h, 0.0, 0.0])
        self._v = np.array([0.0, 0.0, 0.0, 0.0])

        # Actuation & Environment
        g = cfg.environment.gravity
        if plan.slope_deg:
            alpha = math.radians(plan.slope_deg)
            self._gravity = (-g * math.sin(alpha), 0.0, -g * math.cos(alpha))
        else:
            self._gravity = (0.0, 0.0, -g)

        self._kp = getattr(cfg.drive, "kp", 100.0)
        self._kv = getattr(cfg.drive, "kv", 5.0)
        self._max_torque = getattr(cfg.drive, "max_torque", 1e6)
        self._q0 = -self._phases[0]
        self._actuator_target = self._q0
        self._actuator_released = False
        self._applied_joint_torque = 0.0
        self._applied_tx_force = 0.0

        # Pin friction and damping
        self._joint_friction_coeff = getattr(w, "joint_friction_coeff", 0.0)
        self._joint_pin_radius = getattr(w, "joint_pin_radius", 0.003)
        self._foot_radius = w.foot_radius
        self._foot_friction = w.foot_friction
        self._lateral_spacing = w.lateral_spacing

        if plan.softness is not None:
            self._contact_softness = (float(plan.softness[0]), float(plan.softness[1]))
        elif hasattr(cfg, "terrain") and cfg.terrain and cfg.terrain.kind == "sand":
            self._contact_softness = (
                float(cfg.terrain.params.get("stiffness", 2800.0)),
                float(cfg.terrain.params.get("damping", 180.0)),
            )
        elif hasattr(cfg, "terrain") and cfg.terrain and cfg.terrain.kind == "soft":
            self._contact_softness = (
                float(cfg.terrain.params.get("stiffness", 4000.0)),
                float(cfg.terrain.params.get("damping", 120.0)),
            )
        elif hasattr(cfg, "terrain") and cfg.terrain and "stiffness" in cfg.terrain.params:
            self._contact_softness = (
                float(cfg.terrain.params["stiffness"]),
                float(cfg.terrain.params.get("damping", 0.0)),
            )

        self._solver_contact_softness = None
        if hasattr(cfg, "solver") and cfg.solver and getattr(cfg.solver, "contact_stiffness", None) is not None:
            k_stiff = float(cfg.solver.contact_stiffness)
            zeta = float(getattr(cfg.solver, "contact_damping_ratio", 1.0))
            damp_ratio = 2.0 * zeta * math.sqrt(k_stiff)
            self._solver_contact_softness = (self._m_total * k_stiff, self._m_total * damp_ratio)

        body_names = self._inertia.body_names
        foot_names = tuple(f"foot_bar{i}_{self._foot_owner_suffix}" for i in range(n))

        self._info = BuildInfo(
            n_legs=n,
            crank_joint="crank0",
            crank_q0=self._q0,
            actuator="drive",
            hip_height=hip_h,
            bar_mass_total=built.bar_mass_total,
            body_names=body_names,
            foot_names=foot_names,
        )
        return self._info

    def set_param(self, path: str, value: Any) -> None:
        if path == "gravity":
            self._gravity = tuple(float(v) for v in value)
            if self._kind == "pendulum":
                self._params["gravity"] = abs(self._gravity[2])
        elif path == "contact.softness":
            if value is None:
                self._contact_softness = None
            else:
                stiffness, damping = value
                self._contact_softness = (float(stiffness), float(damping))
        elif path in ("terrain.friction", "friction"):
            self._foot_friction = float(value)
            if self._kind == "block":
                self._params["friction"] = float(value)
        else:
            raise KeyError(f"unsupported parameter path '{path}'")

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self._step_once()
            self.time += self.timestep

    def _interp_foot(self, th: float) -> tuple[float, float, float, float, float]:
        idx = (th % math.tau)/self._table_step
        i0 = int(idx) % self._N_TABLE
        s = idx - int(idx)
        c = self._foot_coefficients[i0]
        value = c[0]+s*(c[1]+s*(c[2]+s*(c[3]+s*(c[4]+s*c[5]))))
        deriv = (c[1]+s*(2*c[2]+s*(3*c[3]+s*(4*c[4]+s*5*c[5]))))/self._table_step
        bx, bz = value[2:]
        dbx, dbz = deriv[2:]
        angular = (bx*dbz-bz*dbx)/(bx*bx+bz*bz)
        return float(value[0]), float(value[1]), float(deriv[0]), float(deriv[1]), float(angular)

    def _foot_contact_kinematics(self, leg: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Sphere center and normal/tangent material-point velocity Jacobians."""
        q, d = self._q, self._direction
        fx, fz, dfx, dfz, dbeta = self._interp_foot(self._phases[leg] + d*q[3])
        c, s = math.cos(q[2]), math.sin(q[2])
        rx, rz = c*fx-s*fz, s*fx+c*fz
        jn = np.array([0., 1., rx if not self._pitch_locked else 0., d*(s*dfx+c*dfz)])
        # CCW angular velocity at the bottom of a sphere adds +radius*omega
        # to the horizontal center velocity, for both torso and owner rotation.
        jt = np.array([1., 0., self._foot_radius-rz if not self._pitch_locked else 0.,
                       d*(c*dfx-s*dfz+self._foot_radius*dbeta)])
        return np.array([q[0]+rx, q[1]+rz]), jn, jt

    def _mass_terms(self):
        cache = self._mass_cache
        if cache is None or cache[1] != self._armature or not np.array_equal(cache[0], self._q):
            sample = self._inertia.sample(self._q, self._armature)
            self._mass_cache = (self._q.copy(), self._armature, sample)
        return self._mass_cache[2]

    def mass_matrix(self) -> np.ndarray:
        """Full configuration-dependent mass in X/Z/Phi/psi, before pitch restriction."""
        return self._mass_terms().matrix.copy()

    def _inverse_mass(self, matrix):
        active = [0, 1, 3] if self._pitch_locked else [0, 1, 2, 3]
        inverse = np.zeros((4, 4))
        inverse[np.ix_(active, active)] = np.linalg.inv(matrix[np.ix_(active, active)])
        return inverse

    def _step_once(self) -> None:
        dt = self.timestep
        if self._kind == "pendulum":
            l = self._params["length"]
            gx, gz = self._gravity[0], self._gravity[2]
            th = self._state["theta"]
            w = self._state["omega"]
            alpha = (gz * math.sin(th) + gx * math.cos(th)) / l
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

            on_ground = z <= 0.05 + 1e-9
            if on_ground:
                z = 0.05
                normal_force = max(0.0, -m * gz)
                vz = 0.0
                f_max = mu * normal_force
                f_ext_x = m * gx

                if abs(vx) < 1e-9:
                    if abs(f_ext_x) <= f_max:
                        ax = 0.0
                        vx = 0.0
                    else:
                        ax = (f_ext_x - math.copysign(f_max, f_ext_x)) / m
                        vx += ax * dt
                else:
                    ax = (f_ext_x - math.copysign(f_max, vx)) / m
                    vx_prev = vx
                    vx += ax * dt
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

        elif self._kind == "walker":
            q = self._q
            v = self._v
            if self._pitch_locked:
                q[2] = v[2] = 0.0
            v_before = v.copy()
            d = self._direction
            sample = self._mass_terms()
            matrix = sample.matrix
            gravity = sample.gravity(self._gravity)
            bias = sample.bias(v)
            potential_before = sample.potential(q, self._gravity)

            # 1. Crank Actuation & Joint Torques
            # joint_angle = q0 - d * psi
            q_crank = self._q0 - d * q[3]
            servo_position_torque = -d*self._kp*(self._actuator_target-q_crank)
            ext_crank_torque = -d*self._applied_joint_torque

            # Add internal joint friction and damping on crank (with load-dependent bearing force model)
            # The crank pin transmits drive forces rather than the chassis vertical deadweight
            bearing_force = (
                sum(abs(l.tangent) for l in self._last_foot_loads)
                if self._last_foot_loads
                else 0.0
            )
            load_pin_fric = self._joint_friction_coeff * self._joint_pin_radius * bearing_force
            # Each declared hinge dissipates at its relative angular speed.
            # Project those local torques through the actual joint Jacobian.
            pin_fric = float(self._inertia.joint_friction @ np.abs(sample.joint_ratios)) + self._frictionloss + load_pin_fric
            pin_damp = float(self._inertia.joint_damping @ (sample.joint_ratios**2)) + self._damping
            friction_torque = 0.0
            if abs(v[3]) > 1e-7:
                friction_torque = math.copysign(pin_fric, v[3])

            # Viscous damping is implicit. Restrict the mass to allowed
            # coordinates before inversion; clamping a full inverse is wrong.
            effective = matrix.copy()
            effective[3, 3] += dt*pin_damp
            inverse = self._inverse_mass(effective)
            force = gravity-bias+np.array([self._applied_tx_force, 0., 0., ext_crank_torque-friction_torque])
            v_star = inverse @ (matrix @ v + force*dt)

            # 3. Active Foot Contacts
            active = []
            foot_positions = []
            for i in range(self._n_legs):
                center, jn, jt = self._foot_contact_kinematics(i)
                foot_x, foot_z = center
                y_i = (i - (self._n_legs - 1) / 2) * self._lateral_spacing
                pos_3d = (foot_x, y_i, foot_z)
                foot_positions.append(pos_3d)

                pen = self._foot_radius - foot_z
                if pen > 0:
                    active.append((i, jn, jt, pen, pos_3d))

            self._last_max_penetration = max(0.0, max((a[3] for a in active), default=0.0))

            # 4. Projected Gauss-Seidel for Contact Impulses
            loads_by_leg = {i: FootLoad(0.0, 0.0, (0.0, 0.0, 0.0), 0.0, foot_positions[i]) for i in range(self._n_legs)}
            net_reaction_torque = 0.0

            beta = 0.15  # Existing penetration stabilization; not retuned here.
            cfm_n = 0.0
            is_analytic = type(self._inertia).__name__.startswith("Analytic")
            softness = self._contact_softness if (self._contact_softness is not None or is_analytic) else self._solver_contact_softness
            if softness is not None:
                c_stiff, c_damp = softness
                denom = c_stiff * dt * dt + c_damp * dt
                if denom > 0:
                    cfm_n = beta / denom
            contact_system = dict(
                free_velocity=v_star, inverse_mass=inverse,
                normals=[a[1] for a in active], tangents=[a[2] for a in active],
                targets=[beta*a[3]/dt for a in active], normal_compliance=[cfm_n]*len(active),
                friction=self._foot_friction, motor_enabled=not self._actuator_released,
                motor_desired=servo_position_torque*dt, motor_damping_dt=self._kv*dt,
                motor_limit=None if self._max_torque is None else self._max_torque*dt,
                iterations=self._contact_iterations,
            )
            solution = solve_contacts(**contact_system)
            self._last_contact_solution = solution
            self._last_contact_iterations = solution.iterations
            if not solution.converged:
                # q/time have not advanced: an unresolved impulse cannot be
                # presented as a completed numerical integration step.
                raise ContactConvergenceError(solution, contact_system)
            pn, pt, motor_impulse, v = solution.normal, solution.tangent, solution.motor, solution.velocity
            if not self._actuator_released:
                servo_torque = motor_impulse/dt
                input_torque = servo_torque + ext_crank_torque
                self._last_actuator_force = -d*servo_torque
            else:
                input_torque = ext_crank_torque
                self._last_actuator_force = 0.0
            damping_torque = pin_damp*v[3]
            for idx, (leg_idx, jn, jt, pen, pos_3d) in enumerate(active):
                fn, ft = pn[idx]/dt, pt[idx]/dt
                slip = abs(float(jt @ v))
                loads_by_leg[leg_idx] = FootLoad(fn, abs(ft), (ft, 0.0, fn), slip, pos_3d)
                net_reaction_torque += jn[3]*fn+jt[3]*ft

            if self._pitch_locked:
                v[2] = 0.0
                q[2] = 0.0

            q += v * dt
            self._q = q
            self._v = v
            self._last_foot_loads = [loads_by_leg[i] for i in range(self._n_legs)]
            self._last_constraint_torque = float(net_reaction_torque)

            # Impulse work is P . J(v_before+v_after)/2, not end-slip * force.
            # Inelastic sticking can remove kinetic energy even when end slip
            # is zero. Keep signed normal work so stabilization is not hidden.
            average = .5*(v_before+v)
            after = self._mass_terms()
            # Frozen-configuration acceleration and symplectic q update have
            # a measurable defect: changing M, bias/gravity quadrature and U.
            # Derive these terms independently of the work ledger, and never
            # use this diagnostic to cancel the ordinary audit residual.
            numerical = (.5*float(v @ (after.matrix-matrix) @ v)
                         + float((gravity-bias) @ average)*dt
                         + after.potential(q, self._gravity)-potential_before)
            normal_work = -sum(pn[k]*float(jn @ average) for k,(_,jn,_,_,_) in enumerate(active)) if active else 0.0
            tangent_work = -sum(pt[k]*float(jt @ average) for k,(_,_,jt,_,_) in enumerate(active)) if active else 0.0
            self._last_step_work = StepWork(
                input=float((input_torque*average[3]+self._applied_tx_force*average[0])*dt),
                contact_normal=float(normal_work), contact_tangent=float(tangent_work),
                joint_friction=float(friction_torque*average[3]*dt),
                viscous=float(damping_torque*average[3]*dt),
                numerical=numerical,
            )
            work = self._last_step_work
            self._last_power_balance = PowerBalance(
                contact=work.contact/dt, equality=work.equality/dt,
                joint_friction=work.joint_friction/dt, viscous=work.viscous/dt,
            )

    def snapshot(self) -> Snapshot:
        # Bearing friction depends on the previous loads; controls, armature,
        # model parameters and observation/work state must restore together.
        return Snapshot(backend=self.name, payload={"version": 2, "state": copy.deepcopy(self.__dict__)})

    def restore(self, snap: Snapshot) -> None:
        if snap.backend != self.name:
            raise ValueError(f"snapshot from backend '{snap.backend}', cannot restore to '{self.name}'")
        if snap.payload.get("version") != 2:
            raise ValueError("K2 restore requires a complete version-2 in-memory checkpoint")
        state = copy.deepcopy(snap.payload["state"])
        self.__dict__.clear()
        self.__dict__.update(state)

    def clone(self) -> K2Backend:
        """Clone all model, integration, load-history and work state independently."""
        return copy.deepcopy(self)

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
        elif self._kind == "walker":
            sample = self._mass_terms()
            e_kin = .5*float(self._v @ sample.matrix @ self._v)
            e_pot = sample.potential(self._q, self._gravity)
            return Energies(kinetic=e_kin, potential=e_pot)
        return Energies(kinetic=0.0, potential=0.0)

    def joint_position(self, name: str) -> float:
        if self._kind == "pendulum" and name == "hinge":
            return float(self._state["theta"])
        elif self._kind == "walker":
            if name == "crank0":
                return float(self._q0 - self._direction * self._q[3])
            elif name == "tx":
                return float(self._q[0])
            elif name == "tz":
                return float(self._q[1])
            elif name == "tp" and not self._pitch_locked:
                return float(-self._q[2])
        raise KeyError(f"unknown joint '{name}' for reference '{self._kind}'")

    def joint_velocity(self, name: str) -> float:
        if self._kind == "pendulum" and name == "hinge":
            return float(self._state["omega"])
        elif self._kind == "walker":
            if name == "crank0":
                return float(-self._direction * self._v[3])
            elif name == "tx":
                return float(self._v[0])
            elif name == "tz":
                return float(self._v[1])
            elif name == "tp" and not self._pitch_locked:
                return float(-self._v[2])
        raise KeyError(f"unknown joint '{name}' for reference '{self._kind}'")

    def body_position(self, name: str) -> Vec3:
        if self._kind == "pendulum" and name == "bob":
            l = self._params["length"]
            th = self._state["theta"]
            return (l * math.sin(th), 0.0, -l * math.cos(th))
        elif self._kind == "block" and name == "block":
            return (float(self._state["x"]), 0.0, float(self._state["z"]))
        elif self._kind == "walker" and name in self._info.body_names:
            position = self._mass_terms().body_positions[self._info.body_names.index(name)]
            return tuple(float(x) for x in position)
        raise KeyError(f"unknown body '{name}' for reference '{self._kind}'")

    def body_poses(self) -> tuple[np.ndarray, np.ndarray]:
        if self._kind == "walker":
            sample = self._mass_terms()
            quats = np.zeros((len(sample.body_angles), 4), dtype=np.float32)
            quats[:, 0] = np.cos(sample.body_angles/2)
            quats[:, 2] = -np.sin(sample.body_angles/2)  # CCW in x/z is rotation about -y.
            return sample.body_positions.astype(np.float32), quats
        pos = self.body_position("bob" if self._kind == "pendulum" else "block")
        return np.array([pos]), np.array([[1.0, 0.0, 0.0, 0.0]])

    def contacts(self) -> list[Contact]:
        return []

    def forces(self) -> Forces:
        return Forces(actuators={"drive": self._last_actuator_force}, contact_net=(0.0, 0.0, 0.0), loop_residual=0.0)

    def foot_contacts(self) -> list[bool]:
        if self._kind == "walker":
            return [load.normal > 1e-4 for load in self._last_foot_loads]
        return []

    def foot_loads(self) -> list[FootLoad]:
        return self._last_foot_loads

    def power_balance(self) -> PowerBalance:
        """Average signed transfer rates over the last walker step."""
        return self._last_power_balance

    def step_work(self) -> StepWork:
        if self._kind != "walker":
            raise ValueError("Discrete step work is currently defined for K2 walkers only")
        return self._last_step_work

    def center_of_mass(self) -> Vec3:
        if self._kind == "pendulum":
            return self.body_position("bob")
        elif self._kind == "block":
            return self.body_position("block")
        elif self._kind == "walker":
            sample = self._mass_terms()
            center = self._q[:2]+sample.moment/sample.mass
            return (float(center[0]), 0.0, float(center[1]))
        return (0.0, 0.0, 0.0)

    def constraint_torque(self, joint: str) -> float:
        return self._last_constraint_torque

    def max_penetration(self) -> float:
        return self._last_max_penetration

    def actuator_force(self, name: str) -> float:
        if name == "drive":
            return self._last_actuator_force
        return 0.0

    def describe_scene(self) -> dict:
        return {"backend": self.name, "kind": self._kind}

    def set_actuator_target(self, name: str, value: float) -> None:
        self._actuator_target = float(value)

    def release_actuator(self, name: str) -> None:
        self._actuator_released = True

    def apply_joint_torque(self, name: str, torque: float) -> None:
        if name == "tx":
            self._applied_tx_force = float(torque)
        else:
            self._applied_joint_torque = float(torque)

    def configure_joint(self, name: str, *, armature: float, damping: float, frictionloss: float) -> None:
        if name != "crank0" or not all(math.isfinite(x) and x >= 0 for x in (armature, damping, frictionloss)):
            raise ValueError("K2 crank0 armature, damping and frictionloss must be finite and nonnegative")
        self._armature = float(armature)
        self._damping = float(damping)
        self._frictionloss = float(frictionloss)
        self._mass_cache = None
