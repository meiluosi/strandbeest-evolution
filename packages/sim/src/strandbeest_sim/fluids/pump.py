"""Reciprocating piston pump coupled to crank rotation angle psi.

Models the kinematic displacement, stroke volume variations, dual check valve
dynamics, reaction torque on the drive crank, and multi-cycle charging of PET bottle banks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .constants import (
    DEFAULT_CRITICAL_PRESSURE_RATIO,
    DEFAULT_POLYTROPIC_EXPONENT,
    P_ATM,
    R_AIR,
    T_0,
)
from .network import CheckValve, FluidNetwork, FluidNode
from .storage import PETBottleBank


@dataclass
class PumpCycleResult:
    """Multi-cycle simulation result for crank-driven reciprocating pump charging.

    Attributes
    ----------
    t : np.ndarray
        Time points array [s].
    psi : np.ndarray
        Crank angle array [rad].
    p_cyl : np.ndarray
        Cylinder pressure history [Pa].
    V_cyl : np.ndarray
        Cylinder volume history [m^3].
    p_bottle : np.ndarray
        Bottle manifold pressure history [Pa].
    m_bottle : np.ndarray
        Bottle air mass history [kg].
    tau_pump : np.ndarray
        Crank reaction torque history [N*m].
    work_accumulated : np.ndarray
        Cumulative mechanical crank work integral [J].
    inlet_valve_open : np.ndarray
        Boolean array indicating when inlet valve is open.
    outlet_valve_open : np.ndarray
        Boolean array indicating when outlet valve is open.
    initial_bottle_pressure : float
        Starting bottle bank pressure [Pa].
    final_bottle_pressure : float
        Ending bottle bank pressure [Pa].
    pressure_rise : float
        Net bottle pressure increase [Pa].
    total_crank_work : float
        Total work done on pump by crank shaft integral(tau * dpsi) [J].
    total_pv_work : float
        Total gas indicator work integral(-p_cyl * dV) [J].
    work_conservation_error : float
        Relative difference |W_crank - W_pV| / W_crank [-].
    is_monotonically_increasing_bottle_pressure : bool
        Whether cycle-by-cycle bottle pressure strictly increases.
    mass_pumped : float
        Net mass of air added to bottle storage [kg].
    """

    t: np.ndarray
    psi: np.ndarray
    p_cyl: np.ndarray
    V_cyl: np.ndarray
    p_bottle: np.ndarray
    m_bottle: np.ndarray
    tau_pump: np.ndarray
    work_accumulated: np.ndarray
    inlet_valve_open: np.ndarray
    outlet_valve_open: np.ndarray
    initial_bottle_pressure: float
    final_bottle_pressure: float
    pressure_rise: float
    total_crank_work: float
    total_pv_work: float
    work_conservation_error: float
    is_monotonically_increasing_bottle_pressure: bool
    mass_pumped: float


@dataclass
class CrankReciprocatingPump:
    """Reciprocating piston pump coupled to crank shaft rotation angle psi.

    Parameters
    ----------
    crank_radius : float, default 0.025
        Crank drive throw radius r_pump [m] (stroke S = 2 * r_pump = 50 mm).
    piston_diameter : float, default 0.030
        Cylinder bore diameter D_p [m] (30 mm bore).
    dead_volume_ratio : float, default 0.05
        Clearance volume at TDC as fraction of stroke volume (V_dead = ratio * V_stroke).
    cracking_pressure : float, default 2000.0
        Check valve cracking pressure differential Delta p_crack [Pa] (2 kPa).
    inlet_conductance : float, default 2e-8
        Inlet check valve sonic conductance C_in [m^3/(s*Pa)].
    outlet_conductance : float, default 2e-8
        Outlet check valve sonic conductance C_out [m^3/(s*Pa)].
    b_valves : float, default 0.528
        Critical pressure ratio for valves [-].
    polytropic_exponent : float, default 1.25
        Polytropic exponent n for cylinder air [-].
    smoothing_dp : float, default 0.0
        Smoothing band for check valve transition [Pa].
    """

    crank_radius: float = 0.025  # 25 mm
    piston_diameter: float = 0.030  # 30 mm
    dead_volume_ratio: float = 0.05  # 5% dead volume
    cracking_pressure: float = 2000.0  # 2 kPa
    inlet_conductance: float = 2e-8  # m^3/(s*Pa)
    outlet_conductance: float = 2e-8  # m^3/(s*Pa)
    b_valves: float = DEFAULT_CRITICAL_PRESSURE_RATIO
    polytropic_exponent: float = DEFAULT_POLYTROPIC_EXPONENT
    smoothing_dp: float = 0.0

    @property
    def piston_area(self) -> float:
        """Piston cross-sectional area A_p = (pi / 4) * D_p^2 [m^2]."""
        return 0.25 * math.pi * (self.piston_diameter**2)

    @property
    def stroke(self) -> float:
        """Total piston stroke S = 2 * r_pump [m]."""
        return 2.0 * self.crank_radius

    @property
    def stroke_volume(self) -> float:
        """Swept stroke volume V_stroke = A_p * stroke [m^3]."""
        return self.piston_area * self.stroke

    @property
    def dead_volume(self) -> float:
        """Clearance volume V_dead at Top Dead Center (TDC) [m^3]."""
        return self.dead_volume_ratio * self.stroke_volume

    @property
    def max_volume(self) -> float:
        """Maximum cylinder volume at Bottom Dead Center (BDC) [m^3]."""
        return self.dead_volume + self.stroke_volume

    def piston_displacement(self, psi: float) -> float:
        """Compute piston linear displacement x_p(psi) from BDC toward TDC [m].

        x_p(psi) = r_pump * (1 - cos(psi))
        - At psi = 0 (BDC): x_p = 0.
        - At psi = pi (TDC): x_p = 2 * r_pump.
        """
        return self.crank_radius * (1.0 - math.cos(psi))

    def piston_velocity_per_psi(self, psi: float) -> float:
        """Compute dx_p/dpsi = r_pump * sin(psi) [m/rad]."""
        return self.crank_radius * math.sin(psi)

    def piston_velocity(self, psi: float, omega: float) -> float:
        """Compute linear piston velocity dx_p/dt = r_pump * omega * sin(psi) [m/s]."""
        return self.crank_radius * omega * math.sin(psi)

    def cylinder_volume(self, psi: float) -> float:
        """Compute instantaneous cylinder volume V_p(psi) [m^3].

        V_p(psi) = V_dead + A_p * (2 * r_pump - x_p(psi))
                 = V_dead + A_p * r_pump * (1 + cos(psi))
        - At psi = 0 (BDC): V_p = V_dead + 2 * A_p * r_pump = V_max.
        - At psi = pi (TDC): V_p = V_dead = V_min.
        """
        return self.dead_volume + self.piston_area * (self.stroke - self.piston_displacement(psi))

    def cylinder_volume_derivative_psi(self, psi: float) -> float:
        """Compute derivative dV_p/dpsi = -A_p * r_pump * sin(psi) [m^3/rad]."""
        return -self.piston_area * self.crank_radius * math.sin(psi)

    def cylinder_volume_rate(self, psi: float, omega: float) -> float:
        """Compute volume time rate of change dV_p/dt = -A_p * r_pump * omega * sin(psi) [m^3/s]."""
        return -self.piston_area * self.crank_radius * omega * math.sin(psi)

    def reaction_torque(self, psi: float, p_cyl: float, p_atm: float = P_ATM) -> float:
        """Compute reaction torque exerted by pump on drive crank shaft [N*m].

        tau_pump(psi) = (p_cyl - p_atm) * A_p * (dx_p / dpsi)
                      = (p_cyl - p_atm) * A_p * r_pump * sin(psi)
        """
        dx_dpsi = self.piston_velocity_per_psi(psi)
        f_piston = (p_cyl - p_atm) * self.piston_area
        return f_piston * dx_dpsi

    def mechanical_power(self, psi: float, omega: float, p_cyl: float, p_atm: float = P_ATM) -> float:
        """Compute instantaneous mechanical power delivered to pump [W].

        P = tau_pump * omega = -(p_cyl - p_atm) * dV_p/dt
        """
        tau = self.reaction_torque(psi, p_cyl, p_atm)
        return tau * omega

    def create_network(
        self,
        bottle_bank: PETBottleBank,
        crank_speed_rpm: float = 60.0,
        psi_0: float = 0.0,
        p_atm: float = P_ATM,
        T_atm: float = T_0,
    ) -> FluidNetwork:
        """Create an integrated FluidNetwork containing atmosphere, cylinder, and bottle.

        Parameters
        ----------
        bottle_bank : PETBottleBank
            Storage bottle bank destination.
        crank_speed_rpm : float, default 60.0
            Crank shaft rotational speed [rpm].
        psi_0 : float, default 0.0
            Initial crank angle [rad].
        p_atm : float, default 101325.0
            Atmospheric pressure [Pa].
        T_atm : float, default 293.15
            Atmospheric temperature [K].

        Returns
        -------
        FluidNetwork
            Fully configured fluid network ready for simulation.
        """
        omega = crank_speed_rpm * 2.0 * math.pi / 60.0

        def cyl_volume_func(t: float) -> tuple[float, float]:
            psi = psi_0 + omega * t
            v = self.cylinder_volume(psi)
            dv_dt = self.cylinder_volume_rate(psi, omega)
            return v, dv_dt

        net = FluidNetwork()

        # 1. Atmospheric reservoir (boundary condition)
        atm_node = FluidNode(
            name="atm",
            pressure=p_atm,
            volume=1.0,
            temperature=T_atm,
            is_fixed_pressure=True,
            is_fixed_temperature=True,
        )
        net.add_node(atm_node)

        # 2. Cylinder dynamic node
        v_init = self.cylinder_volume(psi_0)
        cyl_node = FluidNode(
            name="cyl",
            pressure=p_atm,
            volume=v_init,
            temperature=T_atm,
            n=self.polytropic_exponent,
            is_fixed_pressure=False,
            is_fixed_temperature=False,
            volume_func=cyl_volume_func,
        )
        net.add_node(cyl_node)

        # 3. Bottle bank node
        bottle_node = bottle_bank.to_node(name="bottle")
        net.add_node(bottle_node)

        # 4. Inlet check valve: atm -> cyl
        inlet_valve = CheckValve(
            name="inlet_valve",
            node_a="atm",
            node_b="cyl",
            conductance=self.inlet_conductance,
            cracking_pressure=self.cracking_pressure,
            b=self.b_valves,
            smoothing_dp=self.smoothing_dp,
        )
        net.add_element(inlet_valve)

        # 5. Outlet check valve: cyl -> bottle
        outlet_valve = CheckValve(
            name="outlet_valve",
            node_a="cyl",
            node_b="bottle",
            conductance=self.outlet_conductance,
            cracking_pressure=self.cracking_pressure,
            b=self.b_valves,
            smoothing_dp=self.smoothing_dp,
        )
        net.add_element(outlet_valve)

        return net

    def simulate_charging(
        self,
        bottle_bank: PETBottleBank,
        crank_speed_rpm: float = 60.0,
        num_cycles: int = 5,
        dt: float = 1e-4,
        p_atm: float = P_ATM,
        T_atm: float = T_0,
        psi_0: float = 0.0,
    ) -> PumpCycleResult:
        """Simulate multi-cycle crank pump charging of the PET bottle bank.

        Parameters
        ----------
        bottle_bank : PETBottleBank
            PET bottle bank model.
        crank_speed_rpm : float, default 60.0
            Crank shaft rotational speed [rpm].
        num_cycles : int, default 5
            Number of full crank revolutions (cycles).
        dt : float, default 1e-4
            Simulation timestep [s].
        p_atm : float, default 101325.0
            Atmospheric reference pressure [Pa].
        T_atm : float, default 293.15
            Atmospheric ambient temperature [K].
        psi_0 : float, default 0.0
            Initial crank angle [rad].

        Returns
        -------
        PumpCycleResult
            Detailed thermodynamic and kinematic time series and verification metrics.
        """
        omega = crank_speed_rpm * 2.0 * math.pi / 60.0
        period = 2.0 * math.pi / omega
        total_time = num_cycles * period
        n_steps = max(int(math.ceil(total_time / dt)), 1)
        actual_dt = total_time / n_steps

        # Network setup
        net = self.create_network(
            bottle_bank=bottle_bank,
            crank_speed_rpm=crank_speed_rpm,
            psi_0=psi_0,
            p_atm=p_atm,
            T_atm=T_atm,
        )

        inlet_elem = net.elements[0]
        outlet_elem = net.elements[1]

        # Allocation
        t_arr = np.linspace(0.0, total_time, n_steps + 1)
        psi_arr = np.zeros(n_steps + 1)
        p_cyl_arr = np.zeros(n_steps + 1)
        v_cyl_arr = np.zeros(n_steps + 1)
        p_bottle_arr = np.zeros(n_steps + 1)
        m_bottle_arr = np.zeros(n_steps + 1)
        tau_arr = np.zeros(n_steps + 1)
        w_mech_arr = np.zeros(n_steps + 1)
        inlet_open_arr = np.zeros(n_steps + 1, dtype=bool)
        outlet_open_arr = np.zeros(n_steps + 1, dtype=bool)

        # Initial values
        psi_arr[0] = psi_0
        p_cyl_arr[0] = net.nodes["cyl"].pressure
        v_cyl_arr[0] = net.nodes["cyl"].volume
        p_bottle_arr[0] = net.nodes["bottle"].pressure
        m_bottle_arr[0] = net.nodes["bottle"].mass
        tau_arr[0] = self.reaction_torque(psi_0, p_cyl_arr[0], p_atm)
        w_mech_arr[0] = 0.0

        cum_work_mech = 0.0
        cum_work_pv = 0.0

        cycle_end_pressures: list[float] = [p_bottle_arr[0]]
        steps_per_cycle = n_steps // num_cycles

        curr_t = 0.0
        for step_idx in range(1, n_steps + 1):
            # Advance network state by dt using RK4
            net.step(actual_dt, curr_t, method="rk4")
            curr_t = t_arr[step_idx]
            psi = psi_0 + omega * curr_t

            p_cyl = net.nodes["cyl"].pressure
            v_cyl = net.nodes["cyl"].volume
            p_bot = net.nodes["bottle"].pressure
            m_bot = net.nodes["bottle"].mass

            tau = self.reaction_torque(psi, p_cyl, p_atm)
            power_mech = tau * omega
            cum_work_mech += power_mech * actual_dt

            dv_dt = self.cylinder_volume_rate(psi, omega)
            power_pv = -(p_cyl - p_atm) * dv_dt
            cum_work_pv += power_pv * actual_dt

            # Check valve open states
            flows = net.compute_mass_flows()
            inlet_is_open = flows.get("inlet_valve", 0.0) > 1e-12 or (p_atm - p_cyl) >= (self.cracking_pressure - 5.0)
            outlet_is_open = flows.get("outlet_valve", 0.0) > 1e-12 or (p_cyl - p_bot) >= (self.cracking_pressure - 5.0)

            psi_arr[step_idx] = psi
            p_cyl_arr[step_idx] = p_cyl
            v_cyl_arr[step_idx] = v_cyl
            p_bottle_arr[step_idx] = p_bot
            m_bottle_arr[step_idx] = m_bot
            tau_arr[step_idx] = tau
            w_mech_arr[step_idx] = cum_work_mech
            inlet_open_arr[step_idx] = inlet_is_open
            outlet_open_arr[step_idx] = outlet_is_open

            # Record pressure at cycle boundaries
            if step_idx % steps_per_cycle == 0:
                cycle_end_pressures.append(p_bot)

        # Monotonicity check across cycle endpoints
        is_monotonic = all(
            cycle_end_pressures[i] > cycle_end_pressures[i - 1]
            for i in range(1, len(cycle_end_pressures))
        )

        work_err = abs(cum_work_mech - cum_work_pv) / max(abs(cum_work_mech), 1e-12)

        return PumpCycleResult(
            t=t_arr,
            psi=psi_arr,
            p_cyl=p_cyl_arr,
            V_cyl=v_cyl_arr,
            p_bottle=p_bottle_arr,
            m_bottle=m_bottle_arr,
            tau_pump=tau_arr,
            work_accumulated=w_mech_arr,
            inlet_valve_open=inlet_open_arr,
            outlet_valve_open=outlet_open_arr,
            initial_bottle_pressure=p_bottle_arr[0],
            final_bottle_pressure=p_bottle_arr[-1],
            pressure_rise=p_bottle_arr[-1] - p_bottle_arr[0],
            total_crank_work=cum_work_mech,
            total_pv_work=cum_work_pv,
            work_conservation_error=work_err,
            is_monotonically_increasing_bottle_pressure=is_monotonic,
            mass_pumped=m_bottle_arr[-1] - m_bottle_arr[0],
        )
