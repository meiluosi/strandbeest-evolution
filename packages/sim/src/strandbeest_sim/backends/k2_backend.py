"""The K2 independent planar rigid-body physics backend (ADR-0010, V-02).

Independent implementation of the PhysicsBackend protocol (packages/sim/src/strandbeest_sim/backend.py).
Does NOT import MuJoCo. Uses reduced coordinates for Strandbeest walkers and symplectic impulse
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
from ..builder import resolve_spec
from ..config import SimConfig
from ..linkage import solve_pose
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
        self._actuator_target = 0.0
        self._actuator_released = False
        self._applied_joint_torque = 0.0
        self._armature = 0.0
        self._damping = 0.0
        self._frictionloss = 0.0
        self._last_actuator_force = 0.0
        self._last_foot_loads: list[FootLoad] = []
        self._last_power_balance = PowerBalance(0.0, 0.0, 0.0, 0.0)
        self._last_max_penetration = 0.0
        self._last_constraint_torque = 0.0

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
        self._kind = "walker"
        self.time = 0.0
        self._cfg = cfg
        self._plan = plan
        spec = resolve_spec(cfg)
        self._spec = spec

        w = cfg.walker
        u = w.unit
        n = w.legs
        self._u = u
        self._n_legs = n
        self._direction = w.direction
        self._phases = [2 * math.pi * i / n for i in range(n)]

        # Precompute dense circular foot trajectory table
        N_TABLE = 1440
        thetas = np.linspace(0, 2 * math.pi, N_TABLE, endpoint=False)
        raw_pts = [solve_pose(spec, th)[spec.foot] for th in thetas]
        self._px_table = np.array([p[0] * u for p in raw_pts])
        self._pz_table = np.array([p[1] * u for p in raw_pts])
        self._dpx_table = np.gradient(self._px_table, thetas)
        self._dpz_table = np.gradient(self._pz_table, thetas)
        self._N_TABLE = N_TABLE

        lowest = float(np.min(self._pz_table))
        hip_h = -lowest + w.foot_radius
        self._hip_height = hip_h

        # Compute masses and inertias
        def mass_of(length_units: float) -> float:
            return max(w.tube_mass_per_m * length_units * u, w.min_bar_mass)

        crank_mass = mass_of(spec.crank)
        per_leg_mass = crank_mass + sum(mass_of(spec.val(r)) for j in spec.joints for r in j.radii)
        bar_mass_total = n * per_leg_mass
        torso_mass = w.body_mass if w.body_mass is not None else w.mass - bar_mass_total
        if torso_mass <= 0:
            torso_mass = 0.1
        m_total = torso_mass + bar_mass_total
        self._m_total = m_total
        self._torso_mass = torso_mass
        self._bar_mass_total = bar_mass_total

        l_body = w.body_length
        self._pitch_locked = getattr(w, "pitch", "free") == "locked"
        i_pitch = max(1e-4, (1.0 / 12.0) * torso_mass * (l_body**2 + 0.06**2))
        rotor_j = getattr(cfg.drive, "rotor_inertia", 0.0)
        i_crank = max(1e-5, (getattr(w, "crank_inertia", 0.0) or 0.001) + rotor_j)
        self._inv_M = np.array([1.0 / m_total, 1.0 / m_total, 1.0 / i_pitch, 1.0 / i_crank])

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
        self._joint_friction = getattr(w, "joint_friction", 0.0)
        self._joint_damping = getattr(w, "joint_damping", 0.0)
        self._foot_radius = w.foot_radius
        self._foot_friction = w.foot_friction
        self._lateral_spacing = w.lateral_spacing

        body_names = ("torso",) + tuple(f"leg_{i}" for i in range(n))
        foot_names = tuple(f"foot_bar{i}_F0" for i in range(n))

        self._info = BuildInfo(
            n_legs=n,
            crank_joint="crank0",
            crank_q0=self._q0,
            actuator="drive",
            hip_height=hip_h,
            bar_mass_total=bar_mass_total,
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
            pass
        else:
            raise KeyError(f"unsupported parameter path '{path}'")

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self._step_once()
            self.time += self.timestep

    def _interp_foot(self, th: float) -> tuple[float, float, float, float]:
        th_mod = th % (2 * math.pi)
        idx = (th_mod / (2 * math.pi)) * self._N_TABLE
        i0 = int(idx) % self._N_TABLE
        i1 = (i0 + 1) % self._N_TABLE
        frac = idx - int(idx)
        fx = self._px_table[i0] * (1 - frac) + self._px_table[i1] * frac
        fz = self._pz_table[i0] * (1 - frac) + self._pz_table[i1] * frac
        dfx = self._dpx_table[i0] * (1 - frac) + self._dpx_table[i1] * frac
        dfz = self._dpz_table[i0] * (1 - frac) + self._dpz_table[i1] * frac
        return float(fx), float(fz), float(dfx), float(dfz)

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
            d = self._direction
            gx, gz = self._gravity[0], self._gravity[2]

            # 1. Crank Actuation & Joint Torques
            # joint_angle = q0 - d * psi
            q_crank = self._q0 - d * q[3]
            v_crank = -d * v[3]

            if not self._actuator_released:
                # Motor drive position servo: tau_servo = kp * (target - q) - kv * v
                err = self._actuator_target - q_crank
                servo_torque = self._kp * err - self._kv * v_crank
                if abs(servo_torque) > self._max_torque:
                    servo_torque = math.copysign(self._max_torque, servo_torque)
                self._last_actuator_force = servo_torque
                # Actuator torque drives q; crank torque drives forward psi (sign: -d * tau_actuator)
                tau_crank = -d * servo_torque
            else:
                self._last_actuator_force = 0.0
                tau_crank = -d * self._applied_joint_torque

            # Add internal joint friction and damping on crank
            pin_fric = self._joint_friction + self._frictionloss
            pin_damp = self._joint_damping + self._damping
            if abs(v[3]) > 1e-7:
                tau_crank -= math.copysign(pin_fric, v[3]) + pin_damp * v[3]

            # 2. Generalized Forces (Torso X, Torso Z, Torso Pitch, Crank psi)
            f_ext = np.array([
                self._m_total * gx + self._applied_tx_force,
                self._m_total * gz,
                -tau_crank if not self._pitch_locked else 0.0,
                tau_crank,
            ])

            # Unconstrained predicted velocity
            v_star = v + self._inv_M * f_ext * dt
            if self._pitch_locked:
                v_star[2] = 0.0
                q[2] = 0.0

            # 3. Active Foot Contacts
            active = []
            foot_positions = []
            cos_p, sin_p = math.cos(q[2]), math.sin(q[2])

            for i, ph in enumerate(self._phases):
                th_i = ph + d * q[3]
                fx, fz, dfx, dfz = self._interp_foot(th_i)
                # Foot position relative to torso
                rx = cos_p * fx - sin_p * fz
                rz = sin_p * fx + cos_p * fz
                foot_x = q[0] + rx
                foot_z = q[1] + rz
                y_i = (i - (self._n_legs - 1) / 2) * self._lateral_spacing
                pos_3d = (foot_x, y_i, foot_z)
                foot_positions.append(pos_3d)

                pen = self._foot_radius - foot_z
                if pen > 0:
                    # Foot velocity Jacobian rows
                    # vx = v[0] - rz * v[2] + d * (cos_p * dfx - sin_p * dfz) * v[3]
                    # vz = v[1] + rx * v[2] + d * (sin_p * dfx + cos_p * dfz) * v[3]
                    j_psi_x = d * (cos_p * dfx - sin_p * dfz)
                    j_psi_z = d * (sin_p * dfx + cos_p * dfz)
                    jn = np.array([0.0, 1.0, rx if not self._pitch_locked else 0.0, j_psi_z])
                    jt = np.array([1.0, 0.0, -rz if not self._pitch_locked else 0.0, j_psi_x])
                    active.append((i, jn, jt, pen, pos_3d))

            self._last_max_penetration = max(0.0, max((a[3] for a in active), default=0.0))

            # 4. Projected Gauss-Seidel for Contact Impulses
            loads_by_leg = {i: FootLoad(0.0, 0.0, (0.0, 0.0, 0.0), 0.0, foot_positions[i]) for i in range(self._n_legs)}
            total_contact_dissipation = 0.0
            net_reaction_torque = 0.0

            if active:
                pn = [0.0] * len(active)
                pt = [0.0] * len(active)
                v_curr = v_star.copy()
                beta = 0.15  # Baumgarte penetration stabilization

                for _ in range(12):
                    for idx, (leg_idx, jn, jt, pen, _) in enumerate(active):
                        # Normal impulse
                        vn = float(jn @ v_curr)
                        diag_n = float(jn @ (self._inv_M * jn))
                        if diag_n > 1e-9:
                            delta_pn = (-vn + beta * pen / dt) / diag_n
                            new_pn = max(0.0, pn[idx] + delta_pn)
                            d_pn = new_pn - pn[idx]
                            pn[idx] = new_pn
                            v_curr += (self._inv_M * jn) * d_pn

                        # Tangent friction impulse
                        vt = float(jt @ v_curr)
                        diag_t = float(jt @ (self._inv_M * jt))
                        if diag_t > 1e-9:
                            delta_pt = -vt / diag_t
                            trial_pt = pt[idx] + delta_pt
                            max_pt = self._foot_friction * pn[idx]
                            new_pt = max(-max_pt, min(max_pt, trial_pt))
                            d_pt = new_pt - pt[idx]
                            pt[idx] = new_pt
                            v_curr += (self._inv_M * jt) * d_pt

                v = v_curr
                # Record foot loads
                for idx, (leg_idx, jn, jt, pen, pos_3d) in enumerate(active):
                    fn = pn[idx] / dt
                    ft = pt[idx] / dt
                    slip = abs(float(jt @ v))
                    loads_by_leg[leg_idx] = FootLoad(fn, abs(ft), (ft, 0.0, fn), slip, pos_3d)
                    total_contact_dissipation += abs(ft) * slip
                    net_reaction_torque += jn[3] * fn + jt[3] * ft
            else:
                v = v_star

            if self._pitch_locked:
                v[2] = 0.0
                q[2] = 0.0

            q += v * dt
            self._q = q
            self._v = v
            self._last_foot_loads = [loads_by_leg[i] for i in range(self._n_legs)]
            self._last_constraint_torque = float(net_reaction_torque)

            # Dissipation power
            w_crank = abs(v[3])
            fric_power = (self._joint_friction + self._frictionloss) * w_crank + (self._joint_damping + self._damping) * (w_crank**2)
            self._last_power_balance = PowerBalance(
                contact=float(total_contact_dissipation),
                equality=0.0,
                joint_friction=float(fric_power),
                viscous=0.0,
            )

    def snapshot(self) -> Snapshot:
        payload = {
            "time": self.time,
            "kind": self._kind,
            "params": copy.deepcopy(self._params),
            "state": copy.deepcopy(self._state),
            "gravity": self._gravity,
            "actuator_target": self._actuator_target,
            "actuator_released": self._actuator_released,
            "applied_joint_torque": self._applied_joint_torque,
        }
        if self._kind == "walker":
            payload["q"] = self._q.copy()
            payload["v"] = self._v.copy()
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
        self._actuator_target = payload["actuator_target"]
        self._actuator_released = payload["actuator_released"]
        self._applied_joint_torque = payload["applied_joint_torque"]
        if self._kind == "walker":
            self._q = payload["q"].copy()
            self._v = payload["v"].copy()

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
            # kinetic = 0.5 * v^T M v
            m_vec = 1.0 / self._inv_M
            e_kin = 0.5 * float(np.sum(m_vec * (self._v**2)))
            gz = abs(self._gravity[2])
            e_pot = float(self._m_total * gz * (self._q[1] - self._hip_height))
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
        raise KeyError(f"unknown joint '{name}' for reference '{self._kind}'")

    def body_position(self, name: str) -> Vec3:
        if self._kind == "pendulum" and name == "bob":
            l = self._params["length"]
            th = self._state["theta"]
            return (l * math.sin(th), 0.0, -l * math.cos(th))
        elif self._kind == "block" and name == "block":
            return (float(self._state["x"]), 0.0, float(self._state["z"]))
        elif self._kind == "walker" and name == "torso":
            return (float(self._q[0]), 0.0, float(self._q[1]))
        raise KeyError(f"unknown body '{name}' for reference '{self._kind}'")

    def body_poses(self) -> tuple[np.ndarray, np.ndarray]:
        if self._kind == "walker":
            # Torso pose + legs
            torso_pos = np.array([self._q[0], 0.0, self._q[1]])
            half_p = self._q[2] / 2.0
            quat = np.array([math.cos(half_p), 0.0, math.sin(half_p), 0.0])
            n_b = 1 + self._n_legs
            poses = np.zeros((n_b, 3), dtype=np.float32)
            quats = np.zeros((n_b, 4), dtype=np.float32)
            poses[0] = torso_pos
            quats[0] = quat
            for i in range(self._n_legs):
                poses[1 + i] = torso_pos + np.array([0.0, (i - (self._n_legs - 1) / 2) * self._lateral_spacing, 0.0])
                quats[1 + i] = quat
            return poses, quats
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
        return self._last_power_balance

    def center_of_mass(self) -> Vec3:
        if self._kind == "pendulum":
            return self.body_position("bob")
        elif self._kind == "block":
            return self.body_position("block")
        elif self._kind == "walker":
            return (float(self._q[0]), 0.0, float(self._q[1]))
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
        self._armature = float(armature)
        self._damping = float(damping)
        self._frictionloss = float(frictionloss)
        if hasattr(self, "_inv_M"):
            # Update crank inertia with new armature
            m_total = self._m_total
            i_pitch = 1.0 / self._inv_M[2]
            rotor_j = self._armature
            i_crank = max(1e-5, (getattr(self._cfg.walker, "crank_inertia", 0.0) or 0.001) + rotor_j)
            self._inv_M = np.array([1.0 / m_total, 1.0 / m_total, 1.0 / i_pitch, 1.0 / i_crank])
