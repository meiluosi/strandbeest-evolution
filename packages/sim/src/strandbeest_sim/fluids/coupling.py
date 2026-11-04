"""Closed-loop pneumatic-mechanical co-simulation coupler for a single walker (H3-02).

Couples the 1D compressible FluidNetwork (PETBottleBank, CrankReciprocatingPump,
CheckValves / commutated air-motor ports) and morphological reflexes (BistableValve,
PneumaticStepCounter, WaterFeeler, StormAnchor) to the PhysicsBackend stepping loop
in ``runner.py``.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .anchor import StormAnchor, StormAnchorConfig
from .constants import P_ATM, T_0
from .counter import PneumaticStepCounter
from .feeler import WaterFeeler
from .network import BALANCE_CHANNELS, CheckValve, FlowElement, FluidNetwork, FluidNode, iso6358_mass_flow
from .pump import CrankReciprocatingPump
from .storage import PETBottleBank
from .valves import BistableValve


class CommutatedOrifice(FlowElement):
    """Crank-angle and directional-valve commutated orifice for stored-air motor operation."""

    def __init__(
        self,
        name: str,
        node_a: str,
        node_b: str,
        conductance: float,
        is_open_fn: Callable[[], bool],
    ) -> None:
        super().__init__(name=name, node_a=node_a, node_b=node_b, conductance=conductance)
        self._is_open_fn = is_open_fn

    def compute_mass_flow(self, p_a: float, p_b: float, T_a: float, T_b: float) -> float:
        if not self._is_open_fn():
            return 0.0
        return iso6358_mass_flow(
            p1=p_a,
            p2=p_b,
            T1=T_a,
            T2=T_b,
            conductance=self.conductance,
            b=self.b,
        )


PNEUMATICS_SERIES_KEYS = (
    "p_cyl",
    "p_bottle",
    "V_cyl",
    "m_bottle",
    "tau_pump",
    "e_pneumatics",
    "feeler_vacuum",
    "valve_state",
    "step_count",
    "anchor_depth",
)


@dataclass
class PneumaticStepSample:
    """Instantaneous telemetry sample from the coupled pneumatic subsystem."""

    p_cyl: float
    p_bottle: float
    V_cyl: float
    m_bottle: float
    tau_pump: float
    e_pneumatics: float
    feeler_vacuum: float
    valve_state: int
    step_count: int
    anchor_depth: float


class PneumaticCoupler:
    """Bidirectional coupler between a walker PhysicsBackend and its pneumatic network."""

    def __init__(self, sc: Any, psi_start: float = 0.0) -> None:
        pneu = sc.pneumatics
        self.sc = sc
        self.psi_start = psi_start

        self.bottle_bank = PETBottleBank(
            num_bottles=int(pneu.bottle_count),
            volume_per_bottle=float(pneu.bottle_volume_l) * 1e-3,
            precharge_pressure=float(pneu.precharge_pa),
        )
        self.pump = CrankReciprocatingPump(
            crank_radius=0.5 * float(pneu.pump_stroke_m),
            piston_diameter=float(pneu.pump_bore_m),
        )
        self.valve = BistableValve(initial_state=1)
        self.step_counter = PneumaticStepCounter(valve=self.valve)
        self.feeler = WaterFeeler(valve=self.valve, base_altitude=0.05) if pneu.feeler_enabled else None
        self.anchor = (
            StormAnchor(
                StormAnchorConfig(
                    theta_crit_deg=18.0,
                    walker_mass=float(sc.walker.mass),
                    p_tank=max(float(pneu.precharge_pa), 500_000.0),
                )
            )
            if pneu.anchor_enabled
            else None
        )

        # Stored-air propulsion mode activates when a sail-driven walker has zero ambient
        # wind and pre-charged PET bottles above cracking threshold.
        wind_speed = float(getattr(sc.wind, "speed", 0.0) or 0.0)
        wind_gust = float(getattr(sc.wind, "gust", 0.0) or 0.0)
        self.mode = (
            "discharge"
            if (
                sc.drive.kind == "sail"
                and abs(wind_speed) <= 1e-12
                and abs(wind_gust) <= 1e-12
                and float(pneu.precharge_pa) > P_ATM + self.pump.cracking_pressure
            )
            else "charge"
        )
        # In discharge mode, offset cylinder phase by -pi/2 so psi_rel=0 starts at peak
        # positive lever arm (dV/dpsi = +A_p * r_pump > 0) rather than top/bottom dead center.
        self.phase_offset = -0.5 * math.pi if self.mode == "discharge" else 0.0

        self._kin_t0: float = 0.0
        self._kin_psi0: float = self.phase_offset
        self._kin_omega: float = 0.0

        def cyl_volume_func(tau: float) -> tuple[float, float]:
            psi_tau = self._kin_psi0 + self._kin_omega * (tau - self._kin_t0)
            return (
                self.pump.cylinder_volume(psi_tau),
                self.pump.cylinder_volume_rate(psi_tau, self._kin_omega),
            )

        self.network = FluidNetwork(track_mass=True)
        atm_node = FluidNode(
            name="atm",
            pressure=P_ATM,
            volume=1.0,
            temperature=T_0,
            is_fixed_pressure=True,
            is_fixed_temperature=True,
        )
        self.network.add_node(atm_node)

        v_init = self.pump.cylinder_volume(self.phase_offset)
        p_cyl_init = float(pneu.precharge_pa) if self.mode == "discharge" else P_ATM
        cyl_node = FluidNode(
            name="cyl",
            pressure=p_cyl_init,
            volume=v_init,
            temperature=T_0,
            n=self.pump.polytropic_exponent,
            is_fixed_pressure=False,
            is_fixed_temperature=False,
            volume_func=cyl_volume_func,
        )
        self.network.add_node(cyl_node)

        bottle_node = self.bottle_bank.to_node(name="bottle")
        self.network.add_node(bottle_node)

        if self.mode == "charge":
            self.network.add_element(
                CheckValve(
                    name="inlet_valve",
                    node_a="atm",
                    node_b="cyl",
                    conductance=self.pump.inlet_conductance,
                    cracking_pressure=self.pump.cracking_pressure,
                    b=self.pump.b_valves,
                    smoothing_dp=self.pump.smoothing_dp,
                )
            )
            self.network.add_element(
                CheckValve(
                    name="outlet_valve",
                    node_a="cyl",
                    node_b="bottle",
                    conductance=self.pump.outlet_conductance,
                    cracking_pressure=self.pump.cracking_pressure,
                    b=self.pump.b_valves,
                    smoothing_dp=self.pump.smoothing_dp,
                )
            )
        else:
            def _is_power_stroke() -> bool:
                psi_now = self._kin_psi0
                dv_dpsi = self.pump.cylinder_volume_derivative_psi(psi_now)
                return (self.valve.state * dv_dpsi) > 0.0

            self.network.add_element(
                CommutatedOrifice(
                    name="supply_port",
                    node_a="bottle",
                    node_b="cyl",
                    conductance=6.0e-8,
                    is_open_fn=_is_power_stroke,
                )
            )
            self.network.add_element(
                CommutatedOrifice(
                    name="exhaust_port",
                    node_a="cyl",
                    node_b="atm",
                    conductance=8.0e-8,
                    is_open_fn=lambda: not _is_power_stroke(),
                )
            )

        self.initial_bottle_pressure = float(bottle_node.pressure)
        self.initial_total_mass = sum(n.mass for n in self.network.dynamic_nodes)
        self.initial_internal_energy = math.fsum(n.internal_energy_j for n in self.network.dynamic_nodes)
        self.cumulative_balance: dict[str, float] = {k: 0.0 for k in BALANCE_CHANNELS}
        self.e_pneumatics: float = 0.0
        self.last_tau_pump: float = 0.0
        self.last_f_anchor: float = 0.0
        self._psi_before: float = 0.0

    def pre_step(self, sim: Any, drive: Any, t: float) -> tuple[float, float]:
        """Compute and apply pneumatic crank reaction torque and storm anchor holding force before stepping."""
        be = sim.backend
        info = sim.info
        sc = sim.scenario

        psi_rel = sim.psi() - self.psi_start
        self._psi_before = psi_rel
        psi_eff = psi_rel + self.phase_offset

        cyl_node = self.network.get_node("cyl")
        tau_pump = self.pump.reaction_torque(psi_eff, cyl_node.pressure, P_ATM)
        self.last_tau_pump = tau_pump

        # Combine with any external crank torque already applied by the drive (e.g. SailDrive.tau)
        drive_ext_tau = float(getattr(drive, "tau", 0.0)) if sc.drive.kind == "sail" else 0.0
        be.apply_joint_torque(info.crank_joint, -sc.walker.direction * (drive_ext_tau + tau_pump))

        # Storm anchor holding force opposing horizontal motion when deployed
        f_anchor = 0.0
        if self.anchor is not None and self.anchor.is_deployed:
            vx = be.joint_velocity("tx")
            f_hold_max = self.anchor.compute_holding_force(self.anchor.penetration_depth)
            f_anchor = -math.copysign(min(f_hold_max, abs(vx) * 2000.0), vx)
            f_drag = drive.body_drag_force(sim) if hasattr(drive, "body_drag_force") else getattr(drive, "f_drag", 0.0)
            be.apply_joint_torque("tx", f_drag + f_anchor)
        self.last_f_anchor = f_anchor
        return tau_pump, f_anchor

    def post_step(self, sim: Any, observed: Any, drive: Any, dt: float, t: float) -> None:
        """Advance fluid network and morphological reflexes over [t, t + dt] using realized crank motion."""
        psi_after = sim.psi() - self.psi_start
        dpsi = psi_after - self._psi_before
        omega_step = dpsi / dt

        self._kin_t0 = t
        self._kin_psi0 = self._psi_before + self.phase_offset
        self._kin_omega = omega_step

        self.network.step(dt, t, method="rk4")
        for k in BALANCE_CHANNELS:
            self.cumulative_balance[k] += self.network.last_step_balance[k]

        # Mechanical crank work done ON the pump (-tau_pump * dpsi; negative during air-motor expansion)
        self.e_pneumatics += -self.last_tau_pump * dpsi

        # Keep kinematic state aligned with the end of the step
        self._kin_t0 = t + dt
        self._kin_psi0 = psi_after + self.phase_offset

        cyl_node = self.network.get_node("cyl")
        self.step_counter.step(dt, cyl_node.pressure, is_gauge=False)

        if self.feeler is not None:
            raw_water = getattr(self.sc.terrain, "water_level_m", None)
            z_water = float(raw_water) if raw_water is not None else 0.0
            self.feeler.step(dt, z_water=z_water)

        if self.anchor is not None:
            # Extract torso local up-vector in world frame (including terrain slope tilt)
            slope_rad = math.radians(float(getattr(self.sc.terrain, "slope_deg", 0.0) or 0.0))
            _, quats = observed.body_poses()
            if len(quats) > 0:
                w, x, y, z = float(quats[0][0]), float(quats[0][1]), float(quats[0][2]), float(quats[0][3])
                zx = 2.0 * (x * z + w * y)
                zy = 2.0 * (y * z - w * x)
                zz = 1.0 - 2.0 * (x * x + y * y)
                # Rotate by terrain slope so up-vector is relative to gravity vertical
                cos_a, sin_a = math.cos(slope_rad), math.sin(slope_rad)
                z_walker = (zx * cos_a - zz * sin_a, zy, zx * sin_a + zz * cos_a)
            else:
                z_walker = (-math.sin(slope_rad), 0.0, math.cos(slope_rad))
            f_drag = drive.body_drag_force(sim) if hasattr(drive, "body_drag_force") else getattr(drive, "f_drag", 0.0)
            self.anchor.step(dt, z_walker=z_walker, wind_drag_force=f_drag)

    def sample(self) -> PneumaticStepSample:
        """Return current telemetry values for time-series recording."""
        cyl_node = self.network.get_node("cyl")
        bottle_node = self.network.get_node("bottle")
        return PneumaticStepSample(
            p_cyl=float(cyl_node.pressure),
            p_bottle=float(bottle_node.pressure),
            V_cyl=float(cyl_node.volume),
            m_bottle=float(bottle_node.mass),
            tau_pump=float(self.last_tau_pump),
            e_pneumatics=float(self.e_pneumatics),
            feeler_vacuum=float(self.feeler.vacuum) if self.feeler is not None else 0.0,
            valve_state=int(self.valve.state),
            step_count=int(self.step_counter.count),
            anchor_depth=float(self.anchor.penetration_depth) if self.anchor is not None else 0.0,
        )

    def summary_metrics(self) -> dict[str, Any]:
        """Compute end-of-run pneumatic conservation and reflex summary metrics."""
        bottle_node = self.network.get_node("bottle")
        final_mass = sum(n.mass for n in self.network.dynamic_nodes)
        final_internal_energy = math.fsum(n.internal_energy_j for n in self.network.dynamic_nodes)
        mass_residual_kg = final_mass - self.initial_total_mass - self.cumulative_balance["boundary_mass_kg"]
        mass_rel_err = (
            abs(mass_residual_kg) / self.initial_total_mass
            if self.initial_total_mass > 0.0
            else abs(mass_residual_kg)
        )
        energy_residual_j = (
            final_internal_energy
            - self.initial_internal_energy
            - sum(self.cumulative_balance[k] for k in BALANCE_CHANNELS[1:])
        )
        energy_rel_err = (
            abs(energy_residual_j) / self.initial_internal_energy
            if self.initial_internal_energy > 0.0
            else abs(energy_residual_j)
        )
        return {
            "mode": self.mode,
            "initial_bottle_pressure_pa": self.initial_bottle_pressure,
            "final_bottle_pressure_pa": float(bottle_node.pressure),
            "bottle_pressure_rise_pa": float(bottle_node.pressure - self.initial_bottle_pressure),
            "pump_work_j": float(self.e_pneumatics),
            "gas_compression_work_j": float(self.cumulative_balance["compression_work_j"]),
            "stored_internal_energy_delta_j": float(final_internal_energy - self.initial_internal_energy),
            "mass_residual_kg": float(mass_residual_kg),
            "mass_conservation_relative_error": float(mass_rel_err),
            "energy_residual_j": float(energy_residual_j),
            "energy_conservation_relative_error": float(energy_rel_err),
            "valve_state": int(self.valve.state),
            "feeler_tripped": bool(self.feeler.trip_triggered) if self.feeler is not None else False,
            "feeler_max_vacuum_pa": float(self.feeler.vacuum) if self.feeler is not None else 0.0,
            "step_count": int(self.step_counter.count),
            "total_steps_counted": int(self.step_counter.total_steps),
            "anchor_deployed": bool(self.anchor.is_deployed) if self.anchor is not None else False,
            "anchor_trigger_reason": self.anchor.trigger_reason if self.anchor is not None else None,
            "anchor_holding_force_n": (
                float(self.anchor.compute_holding_force(self.anchor.penetration_depth))
                if (self.anchor is not None and self.anchor.is_deployed)
                else 0.0
            ),
        }

    def snapshot(self) -> dict[str, Any]:
        """Capture a complete checkpoint of the pneumatic network and reflex state."""
        return {
            "fluid_state": self.network.get_state().copy(),
            "kin": (self._kin_t0, self._kin_psi0, self._kin_omega),
            "cumulative_balance": dict(self.cumulative_balance),
            "e_pneumatics": self.e_pneumatics,
            "last_tau_pump": self.last_tau_pump,
            "last_f_anchor": self.last_f_anchor,
            "psi_before": self._psi_before,
            "valve": copy.deepcopy(self.valve),
            "step_counter": copy.deepcopy(self.step_counter),
            "feeler": copy.deepcopy(self.feeler),
            "anchor": copy.deepcopy(self.anchor),
        }

    def restore(self, snap: dict[str, Any]) -> None:
        """Restore pneumatic network and reflex state from a checkpoint."""
        self._kin_t0, self._kin_psi0, self._kin_omega = snap["kin"]
        self.network.set_state(np.asarray(snap["fluid_state"], dtype=np.float64), self._kin_t0)
        self.cumulative_balance = dict(snap["cumulative_balance"])
        self.e_pneumatics = float(snap["e_pneumatics"])
        self.last_tau_pump = float(snap["last_tau_pump"])
        self.last_f_anchor = float(snap["last_f_anchor"])
        self._psi_before = float(snap["psi_before"])
        self.valve = copy.deepcopy(snap["valve"])
        self.step_counter = copy.deepcopy(snap["step_counter"])
        self.step_counter.valve = self.valve
        self.feeler = copy.deepcopy(snap["feeler"])
        if self.feeler is not None:
            self.feeler.valve = self.valve
        self.anchor = copy.deepcopy(snap["anchor"])
