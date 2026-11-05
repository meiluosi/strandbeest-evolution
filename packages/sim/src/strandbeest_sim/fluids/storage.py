"""PET bottle compressed air energy storage model.

Models a modular bank of standard commercial polyethylene terephthalate (PET)
bottles connected in parallel as a pneumatic energy accumulator, including thermal
capacitance and convective heat transfer to the ambient environment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .constants import (
    CV_AIR,
    GAMMA_AIR,
    P_ATM,
    R_AIR,
    T_0,
)
from .network import FluidNode


@dataclass
class PETBottleBank:
    """PET bottle compressed air accumulator bank.

    Parameters
    ----------
    num_bottles : int, default 4
        Number of PET bottles manifolded in parallel.
    volume_per_bottle : float, default 0.002
        Internal volume of each individual bottle [m^3] (default 2.0 L).
    precharge_pressure : float, default 101325.0
        Initial atmospheric precharge pressure [Pa].
    max_pressure : float, default 600000.0
        Maximum allowable working pressure [Pa] (0.6 MPa / 6 bar).
    burst_pressure : float, default 800000.0
        Ultimate burst pressure threshold [Pa] (0.8 MPa / 8 bar).
    heat_transfer_coeff : float, default 10.0
        Convective heat transfer coefficient h to ambient air [W/(m^2*K)].
    surface_area_per_bottle : float, default 0.11
        External convective surface area per bottle [m^2] (cylinder D=0.1m, H=0.3m).
    bottle_mass_per_unit : float, default 0.045
        Mass of empty PET bottle [kg] (45 g).
    specific_heat_pet : float, default 1200.0
        Specific heat capacity of PET polymer [J/(kg*K)].
    ambient_temperature : float, default 293.15
        Ambient air temperature T_amb [K] (20 °C).
    polytropic_exponent : float, default 1.25
        Effective polytropic exponent during charging/discharging.
    """

    num_bottles: int = 4
    volume_per_bottle: float = 0.002  # 2.0 L
    precharge_pressure: float = P_ATM
    max_pressure: float = 600_000.0  # 0.6 MPa
    burst_pressure: float = 800_000.0  # 0.8 MPa
    heat_transfer_coeff: float = 10.0  # W/(m^2*K)
    surface_area_per_bottle: float = 0.11  # m^2
    bottle_mass_per_unit: float = 0.045  # kg
    specific_heat_pet: float = 1200.0  # J/(kg*K)
    ambient_temperature: float = T_0  # 293.15 K
    polytropic_exponent: float = 1.25
    h_int: Optional[float] = None  # Internal heat transfer coefficient [W/(m^2*K)]
    h_ext: Optional[float] = None  # External heat transfer coefficient [W/(m^2*K)]
    initial_wall_temperature: Optional[float] = None

    @property
    def total_volume(self) -> float:
        """Total combined storage volume of all bottles in the bank [m^3]."""
        return self.num_bottles * self.volume_per_bottle

    @property
    def total_surface_area(self) -> float:
        """Total convective heat transfer surface area [m^2]."""
        return self.num_bottles * self.surface_area_per_bottle

    @property
    def total_bottle_mass(self) -> float:
        """Total empty mass of the bottle shells [kg]."""
        return self.num_bottles * self.bottle_mass_per_unit

    @property
    def wall_thermal_capacitance(self) -> float:
        """Total thermal heat capacitance of the PET bottle walls [J/K]."""
        return self.total_bottle_mass * self.specific_heat_pet

    def total_thermal_capacitance(self, air_mass: float) -> float:
        """Combined thermal capacitance of enclosed air and PET container walls [J/K]."""
        return self.wall_thermal_capacitance + air_mass * CV_AIR

    def is_overpressure(self, pressure: float) -> bool:
        """Return True if pressure exceeds the maximum safe operating limit (0.6 MPa)."""
        return pressure > self.max_pressure

    def is_burst(self, pressure: float) -> bool:
        """Return True if pressure equals or exceeds the physical burst threshold (0.8 MPa)."""
        return pressure >= self.burst_pressure

    def safety_factor(self, pressure: float) -> float:
        """Burst safety factor relative to current pressure (SF = p_burst / p)."""
        if pressure <= 0.0:
            return float("inf")
        return self.burst_pressure / pressure

    def heat_exchange(self, temperature: float) -> float:
        """Compute convective heat exchange rate with ambient atmosphere [W].

        Q_dot = h * A * (T_amb - T)
        Positive when absorbing heat from ambient (cooling bottle).
        Negative when losing heat to ambient (hot pressurized bottle).
        """
        return self.heat_transfer_coeff * self.total_surface_area * (self.ambient_temperature - temperature)

    def heat_exchange_int(self, T_air: float, T_wall: float) -> float:
        """Internal heat exchange rate Q_int = h_int * A * (T_air - T_wall) [W].

        Positive when heat transfers from enclosed air into the bottle wall.
        """
        h_int = self.h_int if self.h_int is not None else self.heat_transfer_coeff
        return h_int * self.total_surface_area * (T_air - T_wall)

    def heat_exchange_ext(self, T_wall: float) -> float:
        """External heat exchange rate Q_ext = h_ext * A * (T_wall - T_amb) [W].

        Positive when heat transfers from the bottle wall into the ambient environment.
        """
        h_ext = self.h_ext if self.h_ext is not None else self.heat_transfer_coeff
        return h_ext * self.total_surface_area * (T_wall - self.ambient_temperature)

    def stored_mass(self, pressure: float, temperature: float = T_0) -> float:
        """Compute total enclosed air mass using ideal gas equation of state [kg].

        m = p * V / (R * T)
        """
        return (pressure * self.total_volume) / (R_AIR * max(temperature, 1.0))

    def stored_internal_energy(self, pressure: float) -> float:
        """Compute total internal thermodynamic energy of stored gas [J].

        U = m * cv * T = (p * V) / (gamma - 1)
        """
        return (pressure * self.total_volume) / (GAMMA_AIR - 1.0)

    def stored_exergy(self, pressure: float, temperature: float = T_0) -> float:
        """Compute maximum available expansion work (exergy) to atmospheric pressure [J].

        For isothermal expansion to p_atm:
            W_avail = p * V * ln(p / p_atm) - (p - p_atm) * V
        """
        if pressure <= P_ATM:
            return 0.0
        v = self.total_volume
        return pressure * v * math.log(pressure / P_ATM) - (pressure - P_ATM) * v

    def to_node(
        self,
        name: str = "bottle_bank",
        initial_pressure: Optional[float] = None,
        initial_temperature: Optional[float] = None,
        initial_wall_temperature: Optional[float] = None,
    ) -> FluidNode:
        """Create an integrated FluidNode representing this PET bottle bank."""
        p_init = initial_pressure if initial_pressure is not None else self.precharge_pressure
        t_init = initial_temperature if initial_temperature is not None else self.ambient_temperature
        t_wall_init = initial_wall_temperature if initial_wall_temperature is not None else (
            self.initial_wall_temperature if self.initial_wall_temperature is not None else self.ambient_temperature
        )
        init_air_mass = (p_init * self.total_volume) / (R_AIR * max(t_init, 1.0))
        h_int = self.h_int if self.h_int is not None else self.heat_transfer_coeff
        h_ext = self.h_ext if self.h_ext is not None else self.heat_transfer_coeff

        return FluidNode(
            name=name,
            pressure=p_init,
            volume=self.total_volume,
            temperature=t_init,
            mass=init_air_mass,
            n=self.polytropic_exponent,
            is_fixed_pressure=False,
            is_fixed_temperature=False,
            heat_transfer_coeff=self.heat_transfer_coeff,
            heat_transfer_area=self.total_surface_area,
            ambient_temperature=self.ambient_temperature,
            thermal_capacitance=self.total_thermal_capacitance(init_air_mass),
            wall_thermal_capacitance=self.wall_thermal_capacitance,
            T_wall=t_wall_init,
            h_int=h_int,
            h_ext=h_ext,
        )
