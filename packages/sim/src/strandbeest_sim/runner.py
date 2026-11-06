"""Stepping loop, written against the PhysicsBackend protocol. Terrain and drive come from registries; every run returns its
resolved config with the arrays."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .backend import BuildInfo, PhysicsBackend
from .audit_observation import AuditObservation
from .backends import make_backend
from .builder import EntityBuilt, HerdBuilt, build_herd
from .config import Scenario, SimConfig, sim_config
from .fluids.anchor import StormAnchor, StormAnchorConfig
from .fluids.coupling import PNEUMATICS_SERIES_KEYS, PneumaticCoupler
from .fluids.feeler import WaterFeeler, WaterFeelerConfig
from .fluids.tide import DynamicTideField
from .fluids.valves import BistableValve
from .linkage import LinkageSpec
from .registry import drives, metrics, terrains
from .winds import SpatiotemporalWindField


@dataclass
class Result:
    scenario: SimConfig  # the flat configuration that was run
    t: np.ndarray
    psi: np.ndarray  # crank rotation in the walking direction, rad, unwrapped, 0 at the start of driving
    x: np.ndarray  # torso forward position, m
    z: np.ndarray  # torso height, m
    torque: np.ndarray  # crank torque supplied by the drive, N·m (positive = driving the walker forward)
    metrics: dict[str, Any] = field(default_factory=dict)
    stalled: bool = False
    scene: dict | None = None  # geometry for replay
    frames: dict | None = None  # recorded body poses: t, pos (F,B,3), quat (F,B,4), contact (F,feet), foot_pos, foot_force, foot_slip, com
    series: dict = field(default_factory=dict)  # per-sample series beyond the basic five: foot loads, energies, loop residual, ...
    audit_observation: dict | None = None  # complete driven-step support and peak invariants; absent in historical results


@dataclass
class Sim:
    """Everything a terrain / drive / metric extension may touch."""

    scenario: SimConfig
    backend: PhysicsBackend
    info: BuildInfo

    @property
    def q0(self) -> float:
        return self.info.crank_q0

    def psi(self) -> float:
        d = self.scenario.walker.direction
        return -d * (self.backend.joint_position(self.info.crank_joint) - self.q0)


def make_sim(sc: Scenario | SimConfig, backend: str | PhysicsBackend = "mujoco") -> Sim:
    cfg = sim_config(sc)
    be = make_backend(backend) if isinstance(backend, str) else backend
    info = be.build(cfg, terrains.get(cfg.terrain.kind)(cfg))
    return Sim(cfg, be, info)


def run(sc: Scenario | SimConfig | dict, backend: str | PhysicsBackend = "mujoco") -> Result:
    sc = sim_config(sc)
    sim = make_sim(sc, backend)
    be = sim.backend
    info = sim.info
    drive = drives.get(sc.drive.kind)(sim)
    dt = be.timestep
    rec = sc.run.record_every

    t_, psi_, x_, z_, tau_ = [], [], [], [], []
    ser: dict[str, list] = {k: [] for k in ("theta_rad", "loop_residual", "penetration", "foot_normal", "foot_tangent", "foot_slip", "kinetic", "potential",
                                          "e_in", "e_contact", "e_loops", "e_friction", "crank_reaction")}
    e_in = e_contact = e_loops = e_friction = 0.0  # cumulative energy account since the start of driving, J
    f_foot_pos, f_foot_force, f_foot_slip, f_com = [], [], [], []
    frame_every = max(1, round(1.0 / (sc.run.frame_rate * dt))) if sc.run.frame_rate > 0 else 0
    f_t, f_pos, f_quat, f_contact = [], [], [], []
    f_p_bottle, f_p_cyl, f_feeler_vacuum, f_valve_state, f_anchor_depth = [], [], [], [], []
    settle_steps = int(round(sc.run.settle / dt))
    for _ in range(settle_steps):
        drive.control(sim, 0.0, driving=False)
        be.step()
    psi_start = sim.psi()
    target = sc.run.revolutions * 2 * math.pi
    k = 0
    stalled = False
    t = 0.0
    synchronized = callable(getattr(be, "step_observation", None))
    audit_observation = AuditObservation(dt, sc.walker.legs, "force_evaluation" if synchronized else "post_step")
    discrete_work = callable(getattr(be, "step_work", None)) and not synchronized
    extra_work = {name: 0.0 for name in ("e_contact_normal", "e_contact_tangent", "e_numerical")} if discrete_work else {}
    ser.update({name: [] for name in extra_work})
    pneu = PneumaticCoupler(sc, psi_start=psi_start) if sc.pneumatics is not None else None
    if pneu is not None:
        ser.update({name: [] for name in PNEUMATICS_SERIES_KEYS})
    while sim.psi() - psi_start < target:
        drive.control(sim, t, driving=True)
        tau_pump, f_anchor = pneu.pre_step(sim, drive, t) if pneu is not None else (0.0, 0.0)
        omega_before = -sc.walker.direction * be.joint_velocity(info.crank_joint)
        vx_before = be.joint_velocity("tx")
        be.step()
        # MuJoCo observations describe the force-evaluation boundary t_n.
        # Cumulative work is recorded before adding this interval's work.
        if synchronized:
            observed = be.step_observation()
            observed_sim = Sim(sc, observed, info)
            record_time = t
        else:
            observed, observed_sim = be, sim
            record_time = t + dt
            omega = -sc.walker.direction * be.joint_velocity(info.crank_joint)
            vx = be.joint_velocity("tx")
            f_drag = drive.body_drag_force(sim) if hasattr(drive, "body_drag_force") else getattr(drive, "f_drag", 0.0)
            if discrete_work:
                work = be.step_work()
                e_in += work.input
                e_contact += work.contact
                e_loops += work.equality
                e_friction += work.joint_friction + work.viscous
                extra_work["e_contact_normal"] += work.contact_normal
                extra_work["e_contact_tangent"] += work.contact_tangent
                extra_work["e_numerical"] += work.numerical
            else:
                e_in += ((drive.torque(sim) + tau_pump) * omega + (f_drag + f_anchor) * vx) * dt
                pb = be.power_balance()
                e_contact += pb.contact * dt
                e_loops += pb.equality * dt
                e_friction += (pb.joint_friction + pb.viscous) * dt
        if pneu is not None:
            pneu.post_step(sim, observed, drive, dt, t)
        pen = observed.max_penetration()
        viol = observed.loop_residual() if hasattr(observed, "loop_residual") else observed.forces().loop_residual
        loads = observed.foot_loads()
        # A positive contact gap is not penetration. Preserve the original raw
        # telemetry, but aggregate nonnegative depth without hiding NaN values.
        audit_observation.observe(record_time, [f.normal for f in loads], viol, 0. if pen < 0 else pen)
        if k % rec == 0:
            t_.append(record_time)
            psi_.append(observed_sim.psi() - psi_start)
            torso = observed.body_position("torso")
            x_.append(torso[0])
            z_.append(torso[2])
            tau_.append(drive.torque(observed_sim) + tau_pump)
            en = observed.energies()
            for key, val in (("theta_rad", -(observed.joint_position(info.crank_joint)-info.crank_q0)),
                             ("loop_residual", viol), ("penetration", pen), ("foot_normal", [f.normal for f in loads]),
                             ("foot_tangent", [f.tangent for f in loads]), ("foot_slip", [f.slip for f in loads]),
                             ("kinetic", en.kinetic), ("potential", en.potential), ("e_in", e_in), ("e_contact", e_contact),
                             ("e_loops", e_loops), ("e_friction", e_friction), ("crank_reaction", observed.constraint_torque(info.crank_joint))):
                ser[key].append(val)
            for key, val in extra_work.items():
                ser[key].append(val)
            if pneu is not None:
                p_sample = pneu.sample()
                for key in PNEUMATICS_SERIES_KEYS:
                    ser[key].append(getattr(p_sample, key))
        if frame_every and k % frame_every == 0:
            f_t.append(record_time)
            pos, quat = observed.body_poses()
            f_pos.append(pos)
            f_quat.append(quat)
            f_contact.append(observed.foot_contacts())
            f_foot_pos.append([f.pos for f in loads])
            f_foot_force.append([f.force for f in loads])
            f_foot_slip.append([f.slip for f in loads])
            f_com.append(observed.center_of_mass())
            if pneu is not None:
                p_samp = pneu.sample()
                f_p_bottle.append(p_samp.p_bottle)
                f_p_cyl.append(p_samp.p_cyl)
                f_feeler_vacuum.append(p_samp.feeler_vacuum)
                f_valve_state.append(p_samp.valve_state)
                f_anchor_depth.append(p_samp.anchor_depth)
        omega = -sc.walker.direction * be.joint_velocity(info.crank_joint)
        vx = be.joint_velocity("tx")
        f_drag = drive.body_drag_force(sim) if hasattr(drive, "body_drag_force") else getattr(drive, "f_drag", 0.0)
        if synchronized:
            # Implicit servo velocity bias belongs to the step's effective
            # force; a held external sail force has no such derivative.
            torque = drive.step_torque(sim) if hasattr(drive, "step_torque") else drive.torque(sim)
            e_in += ((torque + tau_pump) * (omega_before + omega) + (f_drag + f_anchor) * (vx_before + vx)) * 0.5 * dt
            pb = be.step_power_balance()
            e_contact += pb.contact * dt
            e_loops += pb.equality * dt
            e_friction += (pb.joint_friction + pb.viscous) * dt
        t += dt
        k += 1
        if t > sc.run.max_time:
            stalled = True
            break
        if sc.run.give_up_after and t > sc.run.give_up_after and sim.psi() - psi_start < 0.1:
            stalled = True  # the crank has not moved: the drive cannot start this walker
            break

    if pneu is not None:
        if "p_bottle" in ser and "bottle_pressure_pa" not in ser:
            ser["bottle_pressure_pa"] = ser["p_bottle"]
        if "feeler_vacuum" in ser and "feeler_vacuum_pa" not in ser:
            ser["feeler_vacuum_pa"] = ser["feeler_vacuum"]
        if "anchor_depth" in ser and "anchor_deployed" not in ser:
            ser["anchor_deployed"] = [1.0 if d > 0.01 else 0.0 for d in ser["anchor_depth"]]
    res = Result(sc, np.array(t_), np.array(psi_), np.array(x_), np.array(z_), np.array(tau_), stalled=stalled)
    res.series = {k: np.array(v, dtype=float) for k, v in ser.items() if len(v)}
    if f_t:
        res.scene = be.describe_scene()
        frames_dict = {
            "t": np.array(f_t), "pos": np.array(f_pos, np.float32), "quat": np.array(f_quat, np.float32), "contact": np.array(f_contact, bool),
            "foot_pos": np.array(f_foot_pos, np.float32), "foot_force": np.array(f_foot_force, np.float32),
            "foot_slip": np.array(f_foot_slip, np.float32), "com": np.array(f_com, np.float32)
        }
        if pneu is not None:
            frames_dict.update({
                "p_bottle": np.array(f_p_bottle, np.float32),
                "bottle_pressure_pa": np.array(f_p_bottle, np.float32),
                "p_cyl": np.array(f_p_cyl, np.float32),
                "feeler_vacuum": np.array(f_feeler_vacuum, np.float32),
                "feeler_vacuum_pa": np.array(f_feeler_vacuum, np.float32),
                "valve_state": np.array(f_valve_state, np.int8),
                "anchor_depth": np.array(f_anchor_depth, np.float32),
                "anchor_deployed": (np.array(f_anchor_depth) > 0.01).astype(np.uint8),
            })
        res.frames = frames_dict
    res.audit_observation = audit_observation.document(k)
    res.metrics["max_loop_violation"] = res.audit_observation["max_loop_residual_m"]
    res.metrics["max_penetration"] = res.audit_observation["max_penetration_m"]
    res.metrics["wind_only"] = drives.meta(sc.drive.kind)["energy_source"] == "wind"  # False for the electric test rig (docs/WIND.md)
    if pneu is not None:
        res.metrics["pneumatics"] = pneu.summary_metrics()
    for name in metrics.names():
        res.metrics.update(metrics.get(name)(res))
    return res


@dataclass
class WalkerTrajectory:
    """State trajectory and morphological reflexes of a single Strandbeest in a herd."""

    name: str
    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    psi: np.ndarray
    tilt_deg: np.ndarray
    direction: np.ndarray
    feeler_vacuum: np.ndarray
    feeler_immersed: np.ndarray
    feeler_tripped: np.ndarray
    anchor_deployed: np.ndarray
    anchor_holding_force: np.ndarray
    repulsion_force_x: np.ndarray


@dataclass
class HerdResult:
    """Multi-walker co-simulation result on the Digital Beach."""

    scenario: dict[str, Any]
    t: np.ndarray
    walkers: dict[str, WalkerTrajectory]
    water_levels: np.ndarray
    wind_speeds: dict[str, np.ndarray]
    collisions: list[dict[str, Any]] = field(default_factory=list)
    frames: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    energy_account: dict[str, Any] = field(default_factory=dict)


def run_herd(
    sc: Scenario | dict[str, Any],
    specs: dict[str, LinkageSpec] | None = None,
    wind_field: SpatiotemporalWindField | Callable[[float, float, float], float] | None = None,
    tide_field: DynamicTideField | Callable[[float], float] | None = None,
    duration: float = 3.0,
    dt: float | None = None,
    bumper_distance: float = 0.35,
    repulsion_k: float = 400.0,
    repulsion_c: float = 25.0,
    record_every: int = 2,
    frame_rate: float = 0.0,
) -> HerdResult:
    """Run multi-walker co-simulation in a shared physical world with dynamic wind and tide.

    Supports:
      - Spatial-temporal wind field v_wind(t, x, y) = v0 + A * sin(omega * t + kx * x).
      - Dynamic tide water level z_water(t) = z0 + h_tide * sin(omega_tide * t).
      - Mutual bumper collisions and repulsive forces when walkers bump into each other.
      - Autonomous reflexes:
          * Water feeler trips direction reversal if submerged.
          * Storm anchor deploys holding spike into sand if tilted by pushing or steep dunes.
    """
    from .backends.mujoco_backend import run_herd_mujoco

    return run_herd_mujoco(
        sc=sc,
        specs=specs,
        wind_field=wind_field,
        tide_field=tide_field,
        duration=duration,
        dt=dt,
        bumper_distance=bumper_distance,
        repulsion_k=repulsion_k,
        repulsion_c=repulsion_c,
        record_every=record_every,
        frame_rate=frame_rate,
    )
