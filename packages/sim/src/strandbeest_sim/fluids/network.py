"""1D compressible gas network ODE solver and ISO 6358 pneumatic flow models.

Gas-only lumped control volumes exchange upstream enthalpy through each edge.
The empirical polytropic exponent is an explicit heat closure, not the physical
specific-heat ratio. Isothermal nodes include the thermostat heat required to
hold their temperature. This module does not yet model a separate wall state.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .constants import (
    CP_AIR,
    CV_AIR,
    DEFAULT_CRITICAL_PRESSURE_RATIO,
    DEFAULT_POLYTROPIC_EXPONENT,
    GAMMA_AIR,
    P_ATM,
    R_AIR,
    RHO_0,
    T_0,
)


def iso6358_mass_flow(
    p1: float,
    p2: float,
    T1: float = T_0,
    T2: float = T_0,
    conductance: float = 1e-7,
    b: float = DEFAULT_CRITICAL_PRESSURE_RATIO,
    rho0: float = RHO_0,
    T0: float = T_0,
) -> float:
    """Compute mass flow rate between two nodes using ISO 6358 pneumatic orifice model.

    Parameters
    ----------
    p1 : float
        Absolute pressure at port 1 [Pa].
    p2 : float
        Absolute pressure at port 2 [Pa].
    T1 : float, default 293.15
        Absolute temperature at port 1 [K].
    T2 : float, default 293.15
        Absolute temperature at port 2 [K].
    conductance : float, default 1e-7
        Sonic conductance C [m^3/(s*Pa)].
    b : float, default 0.528
        Critical pressure ratio for sonic choked flow [-].
    rho0 : float, default 1.204
        Normal air density under reference conditions [kg/m^3].
    T0 : float, default 293.15
        ISO 6358 reference temperature (20 °C) [K].

    Returns
    -------
    float
        Signed mass flow rate from port 1 to port 2 [kg/s].
        Positive when p1 > p2 (flow 1 -> 2).
        Negative when p2 > p1 (flow 2 -> 1).
        Zero when p1 == p2.
    """
    delta_p = p1 - p2
    if abs(delta_p) < 1e-9 or conductance <= 0.0:
        return 0.0

    if delta_p > 0.0:
        p_up = p1
        T_up = max(T1, 1.0)
        p_down = max(p2, 0.0)
        direction = 1.0
    else:
        p_up = p2
        T_up = max(T2, 1.0)
        p_down = max(p1, 0.0)
        direction = -1.0

    if p_up <= 0.0:
        return 0.0

    # Pressure ratio r in [0, 1]
    r = min(max(p_down / p_up, 0.0), 1.0)
    temp_corr = math.sqrt(T0 / T_up)

    if r <= b:
        # Choked (sonic) flow
        m_dot = conductance * rho0 * p_up * temp_corr
    else:
        # Subsonic flow with elliptical transition
        term = (r - b) / (1.0 - b)
        term_sq = min(term * term, 1.0)
        psi = math.sqrt(max(0.0, 1.0 - term_sq))
        m_dot = conductance * rho0 * p_up * temp_corr * psi

    return direction * m_dot


def iso6358_mass_flow_derivative_ratio(
    r: float,
    p1: float,
    T1: float = T_0,
    conductance: float = 1e-7,
    b: float = DEFAULT_CRITICAL_PRESSURE_RATIO,
    rho0: float = RHO_0,
    T0: float = T_0,
) -> float:
    """Compute analytical derivative d(m_dot)/dr where r = p2/p1 in [0, 1] (p1 > p2).

    Parameters
    ----------
    r : float
        Pressure ratio p2/p1 in [0, 1].
    p1 : float
        Upstream absolute pressure [Pa].
    T1 : float, default 293.15
        Upstream absolute temperature [K].
    conductance : float, default 1e-7
        Sonic conductance C [m^3/(s*Pa)].
    b : float, default 0.528
        Critical pressure ratio [-].
    rho0 : float, default 1.204
        Normal air density [kg/m^3].
    T0 : float, default 293.15
        Reference temperature [K].

    Returns
    -------
    float
        d(m_dot)/dr [kg/s].
        For r <= b, the derivative is identically 0.0.
        For r > b, the derivative is negative and smoothly approaches 0.0 as r -> b+.
    """
    if r < b:
        return 0.0
    if abs(r - b) < 1e-14:
        return 0.0
    if r >= 1.0:
        return -float("inf")

    term = (r - b) / (1.0 - b)
    term_sq = min(term * term, 1.0)
    denom_sqrt = math.sqrt(max(1e-15, 1.0 - term_sq))
    scale = conductance * rho0 * p1 * math.sqrt(T0 / max(T1, 1.0))
    return -scale * (r - b) / ((1.0 - b) ** 2 * denom_sqrt)


def iso6358_mass_flow_derivative_p2(
    p1: float,
    p2: float,
    T1: float = T_0,
    conductance: float = 1e-7,
    b: float = DEFAULT_CRITICAL_PRESSURE_RATIO,
    rho0: float = RHO_0,
    T0: float = T_0,
) -> float:
    """Compute analytical derivative d(m_dot)/dp2 for downstream pressure p2 (p1 > p2).

    Returns
    -------
    float
        d(m_dot)/dp2 [kg/(s*Pa)].
    """
    if p1 <= 0.0:
        return 0.0
    r = p2 / p1
    dr = iso6358_mass_flow_derivative_ratio(r, p1, T1, conductance, b, rho0, T0)
    return dr / p1


@dataclass(frozen=True)
class FluidEnergyRates:
    """Signed energy rates into one gas control volume, all in watts.

    Flow work is already included in enthalpy; compression_work_w is moving-wall
    work only. Empirical/thermostat heat is reported separately from convection.
    """

    enthalpy_w: float
    compression_work_w: float
    convective_heat_w: float
    polytropic_heat_w: float
    thermostat_heat_w: float

    @property
    def net_energy_w(self) -> float:
        return math.fsum((self.enthalpy_w, self.compression_work_w,
                          self.convective_heat_w, self.polytropic_heat_w,
                          self.thermostat_heat_w))


@dataclass
class FluidNode:
    """Lumped-parameter compressible pneumatic node (chamber / manifold).

    Attributes
    ----------
    name : str
        Unique identifier for the node.
    pressure : float
        Absolute static pressure [Pa].
    volume : float
        Chamber internal volume [m^3].
    temperature : float
        Absolute temperature [K].
    mass : float
        Enclosed gas mass [kg]. If 0, initialized via ideal gas law p*V/(R*T).
    n : float
        Empirical polytropic exponent [-], default 1.25. Its implied heat is
        explicitly accounted for; n=gamma with zero convection is adiabatic.
    is_fixed_pressure : bool
        If True, acts as an infinite reservoir / boundary condition (e.g. atmosphere).
    is_fixed_temperature : bool
        If True, temperature is held constant (isothermal condition).
    heat_transfer_coeff : float
        Convective heat transfer coefficient h [W/(m^2*K)].
    heat_transfer_area : float
        External surface area A [m^2].
    ambient_temperature : float
        Surrounding ambient temperature T_amb [K].
    thermal_capacitance : Optional[float]
        Legacy component metadata [J/K], not used by this gas-only solver.
        Wall heat storage and a coupled wall temperature remain unsupported.
    volume_func : Optional[Callable[[float], tuple[float, float]]]
        Optional dynamic kinematic function t -> (V(t), dV/dt(t)).
    """

    name: str
    pressure: float = P_ATM
    volume: float = 0.001
    temperature: float = T_0
    mass: float = 0.0
    n: float = DEFAULT_POLYTROPIC_EXPONENT
    is_fixed_pressure: bool = False
    is_fixed_temperature: bool = False
    heat_transfer_coeff: float = 0.0
    heat_transfer_area: float = 0.0
    ambient_temperature: float = T_0
    thermal_capacitance: Optional[float] = None
    volume_func: Optional[Callable[[float], tuple[float, float]]] = None
    wall_thermal_capacitance: float = 0.0
    T_wall: float = T_0
    h_int: float = 0.0
    h_ext: float = 0.0

    def __post_init__(self) -> None:
        if self.mass <= 0.0 and self.volume > 0.0 and self.pressure > 0.0:
            self.mass = (self.pressure * self.volume) / (R_AIR * max(self.temperature, 1.0))
        if self.wall_thermal_capacitance > 0.0:
            if self.h_int <= 0.0 and self.heat_transfer_coeff > 0.0:
                self.h_int = self.heat_transfer_coeff
            if self.h_ext <= 0.0 and self.heat_transfer_coeff > 0.0:
                self.h_ext = self.heat_transfer_coeff
            if self.T_wall <= 0.0:
                self.T_wall = self.ambient_temperature

    def update_volume(self, t: float) -> tuple[float, float]:
        """Update node volume from kinematic volume_func if present.

        Returns
        -------
        tuple[float, float]
            (volume, dV/dt) in [m^3, m^3/s].
        """
        if self.volume_func is not None:
            v, dv_dt = self.volume_func(t)
            self.volume = v
            return v, dv_dt
        return self.volume, 0.0

    def compute_heat_transfer(self) -> float:
        """Compute convective heat exchange rate into enclosed gas [W].

        When wall_thermal_capacitance > 0:
            Q_int = h_int * A * (T_air - T_wall)
            Heat flux into enclosed air is -Q_int = h_int * A * (T_wall - T_air).
        Otherwise:
            Q_dot = h * A * (T_amb - T_air).
        """
        if self.wall_thermal_capacitance > 0.0:
            h_int = self.h_int if self.h_int > 0.0 else self.heat_transfer_coeff
            if h_int <= 0.0 or self.heat_transfer_area <= 0.0:
                return 0.0
            return h_int * self.heat_transfer_area * (self.T_wall - self.temperature)

        if self.heat_transfer_coeff <= 0.0 or self.heat_transfer_area <= 0.0:
            return 0.0
        return self.heat_transfer_coeff * self.heat_transfer_area * (self.ambient_temperature - self.temperature)

    def compute_heat_transfer_int(self) -> float:
        """Compute internal heat flux Q_int = h_int * A * (T_air - T_wall) from gas to wall [W]."""
        h_int = self.h_int if self.h_int > 0.0 else self.heat_transfer_coeff
        if h_int <= 0.0 or self.heat_transfer_area <= 0.0:
            return 0.0
        return h_int * self.heat_transfer_area * (self.temperature - self.T_wall)

    def compute_heat_transfer_ext(self) -> float:
        """Compute external heat flux Q_ext = h_ext * A * (T_wall - T_amb) from wall to ambient [W]."""
        h_ext = self.h_ext if self.h_ext > 0.0 else self.heat_transfer_coeff
        if h_ext <= 0.0 or self.heat_transfer_area <= 0.0:
            return 0.0
        return h_ext * self.heat_transfer_area * (self.T_wall - self.ambient_temperature)

    @property
    def gas_internal_energy_j(self) -> float:
        """Gas internal energy pV/(gamma-1) [J]."""
        return self.pressure * self.volume / (GAMMA_AIR - 1.0)

    @property
    def wall_internal_energy_j(self) -> float:
        """Wall thermal internal energy C_wall * T_wall [J]."""
        if self.wall_thermal_capacitance > 0.0:
            return self.wall_thermal_capacitance * self.T_wall
        return 0.0

    @property
    def internal_energy_j(self) -> float:
        """Total thermodynamic internal energy of node (gas + wall) [J]."""
        return self.gas_internal_energy_j + self.wall_internal_energy_j

    def energy_rates(
        self, m_dot_net: float, dV_dt: float = 0.0, Q_dot: float = 0.0,
        *, enthalpy_net_w: Optional[float] = None,
    ) -> FluidEnergyRates:
        """Control-volume first law with a named empirical heat closure.

        The network always supplies H=sum(m_dot*cp*T_upstream). A direct call
        without H assumes all transferred gas has the node's temperature.
        For a non-isothermal node the legacy polytropic law is retained with
        upstream temperatures, and its implied heat is explicit:
          Q_poly = (n/gamma-1) H + (gamma-n)/(gamma-1) p V_dot.
        Supplied Q_dot is real heat and uses the physical cv, independently of n.
        This empirical heat is an assumption, not a measured heat-transfer law.
        """
        if self.volume <= 0.0:
            raise ValueError(f"Node '{self.name}' has non-positive volume: {self.volume}")
        h = CP_AIR * self.temperature * m_dot_net if enthalpy_net_w is None else enthalpy_net_w
        work = -self.pressure * dV_dt
        if self.is_fixed_temperature:
            # d(m cv T)/dt = cv T m_dot when a thermostat holds T constant.
            thermostat = CV_AIR * self.temperature * m_dot_net - h - work - Q_dot
            return FluidEnergyRates(h, work, Q_dot, 0.0, thermostat)
        polytropic_heat = ((self.n / GAMMA_AIR - 1.0) * h
                          + (GAMMA_AIR - self.n) / (GAMMA_AIR - 1.0)
                          * self.pressure * dV_dt)
        return FluidEnergyRates(h, work, Q_dot, polytropic_heat, 0.0)

    def compute_dp_dt(
        self, m_dot_net: float, dV_dt: float = 0.0, Q_dot: float = 0.0,
        *, enthalpy_net_w: Optional[float] = None,
    ) -> float:
        """Pressure rate from d(pV/(gamma-1))/dt = H + Q - p V_dot."""
        if self.is_fixed_pressure:
            return 0.0
        rates = self.energy_rates(m_dot_net, dV_dt, Q_dot, enthalpy_net_w=enthalpy_net_w)
        return ((GAMMA_AIR - 1.0) * rates.net_energy_w - self.pressure * dV_dt) / self.volume

    def compute_dm_dt(self, m_dot_net: float) -> float:
        """Compute mass rate dm/dt [kg/s]."""
        if self.is_fixed_pressure:
            return 0.0
        return m_dot_net


class FlowElement(ABC):
    """Abstract base class for 1D pneumatic flow connections between two nodes."""

    def __init__(
        self,
        name: str,
        node_a: str,
        node_b: str,
        conductance: float,
        b: float = DEFAULT_CRITICAL_PRESSURE_RATIO,
    ) -> None:
        self.name = name
        self.node_a = node_a
        self.node_b = node_b
        self.conductance = conductance
        self.b = b

    @abstractmethod
    def compute_mass_flow(self, p_a: float, p_b: float, T_a: float, T_b: float) -> float:
        """Compute signed mass flow rate from node_a to node_b [kg/s]."""
        pass


class Orifice(FlowElement):
    """Bidirectional ISO 6358 orifice flow connection."""

    def compute_mass_flow(self, p_a: float, p_b: float, T_a: float, T_b: float) -> float:
        return iso6358_mass_flow(
            p1=p_a,
            p2=p_b,
            T1=T_a,
            T2=T_b,
            conductance=self.conductance,
            b=self.b,
        )


class CheckValve(FlowElement):
    """Unidirectional check valve allowing flow ONLY from node_a to node_b.

    Cracking condition: opens when (p_a - p_b) > cracking_pressure.
    Seals strictly (zero flow) when reverse or under cracking threshold.
    """

    def __init__(
        self,
        name: str,
        node_a: str,
        node_b: str,
        conductance: float,
        cracking_pressure: float = 2000.0,
        b: float = DEFAULT_CRITICAL_PRESSURE_RATIO,
        smoothing_dp: float = 0.0,
    ) -> None:
        super().__init__(name, node_a, node_b, conductance, b)
        self.cracking_pressure = cracking_pressure
        self.smoothing_dp = smoothing_dp

    def is_open(self, p_a: float, p_b: float) -> bool:
        """Check whether valve is in cracked/open state."""
        return (p_a - p_b) > self.cracking_pressure

    def compute_mass_flow(self, p_a: float, p_b: float, T_a: float, T_b: float) -> float:
        delta_p = p_a - p_b
        eff_dp = delta_p - self.cracking_pressure

        if self.smoothing_dp <= 0.0:
            if eff_dp <= 0.0:
                return 0.0
            factor = 1.0
        else:
            if eff_dp <= -self.smoothing_dp:
                return 0.0
            elif eff_dp >= self.smoothing_dp:
                factor = 1.0
            else:
                s = eff_dp / self.smoothing_dp
                factor = 0.5 + 0.5 * math.sin(0.5 * math.pi * s)

        if delta_p <= 0.0:
            return 0.0

        base_flow = iso6358_mass_flow(
            p1=p_a,
            p2=p_b,
            T1=T_a,
            T2=T_b,
            conductance=self.conductance,
            b=self.b,
        )
        return factor * max(0.0, base_flow)


@dataclass
class FluidSimulationResult:
    """Gas-only histories and a signed boundary/heat/work ledger.

    mass_conservation_relative_error includes boundary exchange, so filling an
    open tank does not count as a conservation failure. balance contains the
    cumulative channels in BALANCE_CHANNELS plus internal_energy_j and signed
    mass_residual_kg/energy_residual_j. Integration error is exposed, not removed.
    Vessel-wall heat storage and full mechanical coupling are not represented.
    """

    t: np.ndarray
    pressures: dict[str, np.ndarray]
    volumes: dict[str, np.ndarray]
    temperatures: dict[str, np.ndarray]
    masses: dict[str, np.ndarray]
    total_mass: np.ndarray
    mass_conservation_relative_error: float
    balance: dict[str, np.ndarray] = field(default_factory=dict)
    wall_temperatures: dict[str, np.ndarray] = field(default_factory=dict)


# Integrated with the same RK stages as p, V and m. These are signed inputs to
# dynamic gas nodes; exchanges between two dynamic nodes cancel in the totals.
BALANCE_CHANNELS = (
    "boundary_mass_kg", "external_enthalpy_j", "compression_work_j",
    "convective_heat_j", "polytropic_heat_j", "thermostat_heat_j",
)


class FluidNetwork:
    """1D compressible pneumatic network ODE solver.

    Manages interconnected fluid nodes and flow elements, computes nodal mass
    balances, and solves pressure and volume dynamics via standard or stiff ODE integration.
    """

    def __init__(self, track_mass: bool = True) -> None:
        self.nodes: dict[str, FluidNode] = {}
        self.elements: list[FlowElement] = []
        self._dynamic_node_names: list[str] = []
        self.track_mass = track_mass
        self.last_step_balance: dict[str, float] = {}

    def add_node(self, node: FluidNode) -> None:
        """Add a fluid node to the network."""
        if node.name in self.nodes:
            raise ValueError(f"Node '{node.name}' already exists in network")
        if not self.track_mass and not node.is_fixed_pressure and not node.is_fixed_temperature:
            raise ValueError("Non-isothermal dynamic nodes require track_mass=True")
        self.nodes[node.name] = node
        if not node.is_fixed_pressure:
            self._dynamic_node_names.append(node.name)

    def add_element(self, element: FlowElement) -> None:
        """Add a flow element (orifice, valve, pipe) to the network."""
        if element.node_a not in self.nodes:
            raise KeyError(f"Element '{element.name}' references non-existent node '{element.node_a}'")
        if element.node_b not in self.nodes:
            raise KeyError(f"Element '{element.name}' references non-existent node '{element.node_b}'")
        self.elements.append(element)

    def get_node(self, name: str) -> FluidNode:
        """Retrieve node by name."""
        return self.nodes[name]

    @property
    def dynamic_nodes(self) -> list[FluidNode]:
        """List of non-boundary dynamic nodes."""
        return [self.nodes[name] for name in self._dynamic_node_names]

    @property
    def wall_nodes(self) -> list[FluidNode]:
        """List of dynamic nodes with explicit wall thermal capacitance."""
        return [node for node in self.dynamic_nodes if node.wall_thermal_capacitance > 0.0]

    def get_state(self) -> np.ndarray:
        """Extract state vector y for dynamic nodes.

        Layout:
        - If no wall nodes:
            - If track_mass is False: [p_1, ..., p_K, V_1, ..., V_K] (length 2K)
            - If track_mass is True:  [p_1, ..., p_K, V_1, ..., V_K, m_1, ..., m_K] (length 3K)
        - If W wall nodes:
            - If track_mass is False: [p_1, ..., p_K, V_1, ..., V_K, T_wall_1, ..., T_wall_W] (length 2K + W)
            - If track_mass is True:  [p_1, ..., p_K, V_1, ..., V_K, m_1, ..., m_K, T_wall_1, ..., T_wall_W] (length 3K + W)
        """
        dyn = self.dynamic_nodes
        wn = self.wall_nodes
        p = [n.pressure for n in dyn]
        v = [n.volume for n in dyn]
        tw = [n.T_wall for n in wn]
        if self.track_mass:
            m = [n.mass for n in dyn]
            return np.array(p + v + m + tw, dtype=np.float64)
        return np.array(p + v + tw, dtype=np.float64)

    def set_state(self, y: np.ndarray, t: float = 0.0) -> None:
        """Update node pressures, volumes, masses, temperatures, and wall temperatures from state vector y."""
        dyn = self.dynamic_nodes
        wn = self.wall_nodes
        k = len(dyn)
        w = len(wn)
        valid_lengths = {k, 2 * k, 3 * k}
        if w > 0:
            valid_lengths.update({2 * k + w, 3 * k + w})
        if len(y) not in valid_lengths or not np.all(np.isfinite(y)):
            raise ValueError("Invalid fluid state length or non-finite state")
        if len(y) not in (3 * k, 3 * k + w) and any(not node.is_fixed_temperature for node in dyn):
            raise ValueError("Non-isothermal fluid state requires pressure, volume and mass")

        if len(y) in (3 * k, 3 * k + w):
            for i, node in enumerate(dyn):
                node.pressure = float(y[i])
                node.volume = float(y[k + i])
                node.mass = float(y[2 * k + i])
                node.update_volume(t)
                if not node.is_fixed_temperature and node.mass > 0.0:
                    node.temperature = (node.pressure * node.volume) / (node.mass * R_AIR)
            if len(y) == 3 * k + w:
                for j, wnode in enumerate(wn):
                    wnode.T_wall = float(y[3 * k + j])
        elif len(y) in (2 * k, 2 * k + w):
            for i, node in enumerate(dyn):
                node.pressure = float(y[i])
                node.volume = float(y[k + i])
                node.update_volume(t)
                if node.is_fixed_temperature:
                    node.mass = (node.pressure * node.volume) / (R_AIR * node.temperature)
                else:
                    if node.mass > 0.0:
                        node.temperature = (node.pressure * node.volume) / (node.mass * R_AIR)
                    else:
                        node.mass = (node.pressure * node.volume) / (R_AIR * node.temperature)
            if len(y) == 2 * k + w:
                for j, wnode in enumerate(wn):
                    wnode.T_wall = float(y[2 * k + j])
        elif len(y) == k:
            for i, node in enumerate(dyn):
                node.pressure = float(y[i])
                node.update_volume(t)
                if node.is_fixed_temperature:
                    node.mass = (node.pressure * node.volume) / (R_AIR * node.temperature)
                elif node.mass > 0.0:
                    node.temperature = (node.pressure * node.volume) / (node.mass * R_AIR)
        for node in dyn:
            values = [node.pressure, node.volume, node.mass, node.temperature]
            if node.wall_thermal_capacitance > 0.0:
                values.append(node.T_wall)
            if not all(math.isfinite(value) and value > 0.0 for value in values):
                raise ValueError(f"Non-positive thermodynamic state or non-finite value in node '{node.name}'; reduce dt")

    def compute_mass_flows(self) -> dict[str, float]:
        """Compute mass flow rates for all elements based on current nodal states."""
        flows: dict[str, float] = {}
        for elem in self.elements:
            na = self.nodes[elem.node_a]
            nb = self.nodes[elem.node_b]
            flow = elem.compute_mass_flow(na.pressure, nb.pressure, na.temperature, nb.temperature)
            flows[elem.name] = flow
        return flows

    def compute_net_mass_flows(self) -> dict[str, float]:
        """Compute net mass flow rate (m_dot_in - m_dot_out) for each node [kg/s]."""
        return self.compute_node_fluxes()[0]

    def compute_node_fluxes(self) -> tuple[dict[str, float], dict[str, float]]:
        """Signed nodal mass [kg/s] and upstream enthalpy [W] fluxes.

        Each edge transfers the very same enthalpy out of its donor and into
        its receiver, including when its signed flow reverses.
        """
        net_flows = {name: 0.0 for name in self.nodes}
        net_enthalpy = {name: 0.0 for name in self.nodes}
        for elem in self.elements:
            na = self.nodes[elem.node_a]
            nb = self.nodes[elem.node_b]
            flow = elem.compute_mass_flow(na.pressure, nb.pressure, na.temperature, nb.temperature)
            # flow > 0 means A -> B (leaves A, enters B)
            net_flows[elem.node_a] -= flow
            net_flows[elem.node_b] += flow
            upstream_temperature = na.temperature if flow >= 0.0 else nb.temperature
            enthalpy = flow * CP_AIR * upstream_temperature
            net_enthalpy[elem.node_a] -= enthalpy
            net_enthalpy[elem.node_b] += enthalpy
        return net_flows, net_enthalpy

    def derivatives(self, t: float, y: np.ndarray) -> np.ndarray:
        """Compute time derivatives dy/dt for the state vector."""
        return self._derivatives_and_balance(t, y)[0]

    def _derivatives_and_balance(self, t: float, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.set_state(y, t)
        dyn = self.dynamic_nodes
        wn = self.wall_nodes
        k = len(dyn)
        w = len(wn)
        net_flows, net_enthalpy = self.compute_node_fluxes()

        dp_dt = np.zeros(k, dtype=np.float64)
        dv_dt = np.zeros(k, dtype=np.float64)
        dm_dt = np.zeros(k, dtype=np.float64)
        dt_wall_dt = np.zeros(w, dtype=np.float64)
        balance = np.zeros(len(BALANCE_CHANNELS), dtype=np.float64)

        for i, node in enumerate(dyn):
            # Volume and kinematic volume derivative
            _, dv_i = node.update_volume(t)
            dv_dt[i] = dv_i
            m_dot_net = net_flows[node.name]
            q_dot = node.compute_heat_transfer()

            rates = node.energy_rates(m_dot_net, dv_i, q_dot, enthalpy_net_w=net_enthalpy[node.name])
            dp_dt[i] = ((GAMMA_AIR - 1.0) * rates.net_energy_w - node.pressure * dv_i) / node.volume
            dm_dt[i] = node.compute_dm_dt(m_dot_net)

            # Heat exchange with external ambient environment
            if node.wall_thermal_capacitance > 0.0:
                h_ext = node.h_ext if node.h_ext > 0.0 else node.heat_transfer_coeff
                q_ambient = h_ext * node.heat_transfer_area * (node.ambient_temperature - node.T_wall)
            else:
                q_ambient = rates.convective_heat_w

            balance += (m_dot_net, rates.enthalpy_w, rates.compression_work_w,
                        q_ambient, rates.polytropic_heat_w, rates.thermostat_heat_w)

        for j, wnode in enumerate(wn):
            q_int = wnode.compute_heat_transfer_int()
            q_ext = wnode.compute_heat_transfer_ext()
            dt_wall_dt[j] = (q_int - q_ext) / wnode.wall_thermal_capacitance

        if len(y) == 3 * k + w:
            return np.concatenate([dp_dt, dv_dt, dm_dt, dt_wall_dt]), balance
        elif len(y) == 3 * k:
            return np.concatenate([dp_dt, dv_dt, dm_dt]), balance
        elif len(y) == 2 * k + w:
            return np.concatenate([dp_dt, dv_dt, dt_wall_dt]), balance
        elif len(y) == 2 * k:
            return np.concatenate([dp_dt, dv_dt]), balance
        return dp_dt, balance

    def step(self, dt: float, t: float = 0.0, method: str = "rk4") -> dict[str, float]:
        """Advance network state by a single timestep dt (ideal for co-simulation).

        Parameters
        ----------
        dt : float
            Timestep size [s].
        t : float, default 0.0
            Current simulation time [s].
        method : str, default 'rk4'
            Integration scheme: 'rk4' (Runge-Kutta 4th order) or 'euler'.

        Returns
        -------
        dict[str, float]
            Mapping of node name -> new pressure [Pa].
        """
        if not math.isfinite(dt) or dt <= 0.0 or not math.isfinite(t):
            raise ValueError("Fluid step requires positive finite dt and finite t")
        if method not in ("rk4", "euler"):
            raise ValueError(f"Unsupported fluid integration method: {method}")
        y = self.get_state()
        try:
            if method == "rk4":
                k1, b1 = self._derivatives_and_balance(t, y)
                k2, b2 = self._derivatives_and_balance(t + 0.5 * dt, y + 0.5 * dt * k1)
                k3, b3 = self._derivatives_and_balance(t + 0.5 * dt, y + 0.5 * dt * k2)
                k4, b4 = self._derivatives_and_balance(t + dt, y + dt * k3)
                y_new = y + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
                integrated_balance = (dt / 6.0) * (b1 + 2.0 * b2 + 2.0 * b3 + b4)
            else:
                k1, b1 = self._derivatives_and_balance(t, y)
                y_new = y + dt * k1
                integrated_balance = dt * b1
            self.set_state(y_new, t + dt)
        except Exception:
            # A rejected RK stage must not leave its partial state as a new initial condition.
            self.set_state(y, t)
            raise
        self.last_step_balance = dict(zip(BALANCE_CHANNELS, map(float, integrated_balance)))
        return {name: node.pressure for name, node in self.nodes.items()}

    def simulate(
        self,
        t_span: tuple[float, float],
        dt: float = 1e-4,
        method: str = "rk4",
    ) -> FluidSimulationResult:
        """Simulate pneumatic network over time interval t_span.

        Parameters
        ----------
        t_span : tuple[float, float]
            (t_start, t_end) in seconds.
        dt : float, default 1e-4
            Time step for fixed-step RK4 integration [s].
        method : str, default 'rk4'
            Integration method.

        Returns
        -------
        FluidSimulationResult
            Time histories of pressures, volumes, temperatures, masses, and conservation metrics.
        """
        t0, t1 = t_span
        if not all(math.isfinite(value) for value in (t0, t1, dt)) or t1 <= t0 or dt <= 0:
            raise ValueError("Fluid simulation requires finite t_end > t_start and positive dt")
        self.set_state(self.get_state(), t0)
        n_steps = max(int(math.ceil((t1 - t0) / dt)), 1)
        t_arr = np.linspace(t0, t1, n_steps + 1)
        actual_dt = (t1 - t0) / n_steps

        all_names = list(self.nodes.keys())
        p_hist = {name: np.zeros(n_steps + 1) for name in all_names}
        v_hist = {name: np.zeros(n_steps + 1) for name in all_names}
        t_hist = {name: np.zeros(n_steps + 1) for name in all_names}
        m_hist = {name: np.zeros(n_steps + 1) for name in all_names}
        wall_names = [name for name, node in self.nodes.items() if node.wall_thermal_capacitance > 0.0]
        wall_t_hist = {name: np.zeros(n_steps + 1) for name in wall_names}
        tot_mass = np.zeros(n_steps + 1)
        balance = {key: np.zeros(n_steps + 1) for key in BALANCE_CHANNELS}
        balance["internal_energy_j"] = np.zeros(n_steps + 1)
        balance["gas_internal_energy_j"] = np.zeros(n_steps + 1)
        balance["wall_internal_energy_j"] = np.zeros(n_steps + 1)

        # Initial state recording
        for name, node in self.nodes.items():
            p_hist[name][0] = node.pressure
            v_hist[name][0] = node.volume
            t_hist[name][0] = node.temperature
            m_hist[name][0] = node.mass
        for name in wall_names:
            wall_t_hist[name][0] = self.nodes[name].T_wall
        tot_mass[0] = sum(self.nodes[name].mass for name in self._dynamic_node_names)
        balance["internal_energy_j"][0] = math.fsum(node.internal_energy_j for node in self.dynamic_nodes)
        balance["gas_internal_energy_j"][0] = math.fsum(node.gas_internal_energy_j for node in self.dynamic_nodes)
        balance["wall_internal_energy_j"][0] = math.fsum(node.wall_internal_energy_j for node in self.dynamic_nodes)

        curr_t = t0
        for step_idx in range(1, n_steps + 1):
            self.step(actual_dt, curr_t, method=method)
            curr_t = t_arr[step_idx]

            for name, node in self.nodes.items():
                p_hist[name][step_idx] = node.pressure
                v_hist[name][step_idx] = node.volume
                t_hist[name][step_idx] = node.temperature
                m_hist[name][step_idx] = node.mass
            for name in wall_names:
                wall_t_hist[name][step_idx] = self.nodes[name].T_wall
            tot_mass[step_idx] = sum(self.nodes[name].mass for name in self._dynamic_node_names)
            for key in BALANCE_CHANNELS:
                balance[key][step_idx] = balance[key][step_idx - 1] + self.last_step_balance[key]
            balance["internal_energy_j"][step_idx] = math.fsum(node.internal_energy_j for node in self.dynamic_nodes)
            balance["gas_internal_energy_j"][step_idx] = math.fsum(node.gas_internal_energy_j for node in self.dynamic_nodes)
            balance["wall_internal_energy_j"][step_idx] = math.fsum(node.wall_internal_energy_j for node in self.dynamic_nodes)

        balance["mass_residual_kg"] = tot_mass - tot_mass[0] - balance["boundary_mass_kg"]
        balance["energy_residual_j"] = (balance["internal_energy_j"] - balance["internal_energy_j"][0]
                                        - sum(balance[key] for key in BALANCE_CHANNELS[1:]))
        initial_mass = tot_mass[0]
        if initial_mass > 0.0:
            rel_err = float(np.max(np.abs(balance["mass_residual_kg"])) / initial_mass)
        else:
            rel_err = float(np.max(np.abs(balance["mass_residual_kg"])))

        return FluidSimulationResult(
            t=t_arr,
            pressures=p_hist,
            volumes=v_hist,
            temperatures=t_hist,
            masses=m_hist,
            total_mass=tot_mass,
            mass_conservation_relative_error=rel_err,
            balance=balance,
            wall_temperatures=wall_t_hist,
        )
