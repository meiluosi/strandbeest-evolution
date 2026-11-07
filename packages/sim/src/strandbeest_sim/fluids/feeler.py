"""Theo Jansen water feeler ("watervoeler") morphological reflex model.

A narrow open-ended sensing tube hangs from the Strandbeest chassis, oscillating
near ground level as the linkage cycles.
A continuous pneumatic suction draws a slight airflow through the tube.

- In air:
  Low air viscosity (1.82e-5 Pa*s) allows free laminar flow via Hagen-Poiseuille resistance.
  The internal vacuum is negligible: |p_tube - p_atm| < 500 Pa (< 1 kPa).

- In water (z_tip <= z_water):
  Water contacts the tip; high water dynamic viscosity (1.002e-3 Pa*s, ~55x air)
  and capillary meniscus seal the opening. The suction pump rapidly evacuates the
  tube and sensing chamber, pulling gauge pressure below -25 kPa within 50 ms.

- Reflex response:
  The resulting vacuum pulse trips the bistable direction slide valve, reversing
  the walking crank direction to escape the rising tide.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .valves import BistableValve


@dataclass
class WaterFeelerConfig:
    """Physical parameters for the water sensor feeler reflex.

    Attributes:
        tube_diameter: Inner bore diameter of sensing tube (m). Default 3 mm.
        tube_length: Total length of sensing tube (m). Default 0.5 m.
        chamber_volume: Additional dead volume of sensing chamber / sensor diaphragm (m^3).
        suction_flow_rate: Steady volumetric suction rate drawn by intake pump (m^3/s).
        mu_air: Dynamic viscosity of air at 20 C (Pa*s).
        mu_water: Dynamic viscosity of water at 20 C (Pa*s).
        surface_tension_water: Surface tension of water-air interface (N/m).
        water_contact_angle: Meniscus contact angle on tube wall (radians).
        gamma_air: Ratio of specific heats for adiabatic/polytropic air decompression.
        p_atm: Standard atmospheric pressure (Pa absolute).
        vacuum_trip_threshold: Gauge pressure below which reverse reflex trips (Pa gauge).
        oscillation_amplitude: Vertical stroke amplitude of oscillating feeler tip (m).
        oscillation_frequency: Oscillation frequency of leg stride (rad/s).
    """

    tube_diameter: float = 0.003  # 3 mm
    tube_length: float = 0.5  # 0.5 m
    chamber_volume: float = 4.5e-6  # 4.5 cm^3 (total sensing volume ~8 cm^3)
    suction_flow_rate: float = 5.0e-5  # 50 cm^3/s = 0.05 L/s = 3 L/min
    mu_air: float = 1.82e-5  # Pa*s
    mu_water: float = 1.002e-3  # Pa*s (~55x air)
    surface_tension_water: float = 0.0728  # N/m
    water_contact_angle: float = 0.0  # radians (complete wetting)
    gamma_air: float = 1.4  # adiabatic expansion
    p_atm: float = 101325.0  # Pa absolute
    vacuum_trip_threshold: float = -25000.0  # -25 kPa gauge
    oscillation_amplitude: float = 0.04  # 4 cm vertical oscillation
    oscillation_frequency: float = 2.0  # rad/s


class WaterFeeler:
    """Theo Jansen water feeler reflex mechanism with Hagen-Poiseuille fluidics."""

    def __init__(
        self,
        config: WaterFeelerConfig | None = None,
        valve: BistableValve | None = None,
        base_altitude: float = 0.05,
    ) -> None:
        self.config = config or WaterFeelerConfig()
        self.valve = valve
        self.base_altitude = base_altitude  # Mean tip elevation above ground (m)

        # Geometric calculations
        self._tube_area = math.pi * (self.config.tube_diameter / 2.0) ** 2
        self._tube_volume = self._tube_area * self.config.tube_length
        self._total_volume = self._tube_volume + self.config.chamber_volume

        # Hagen-Poiseuille hydrodynamic resistances: R = 128 * mu * L / (pi * d^4)
        pi_d4 = math.pi * (self.config.tube_diameter**4)
        self._r_air = (128.0 * self.config.mu_air * self.config.tube_length) / pi_d4
        self._r_water = (128.0 * self.config.mu_water * self.config.tube_length) / pi_d4

        # Capillary entry pressure: p_cap = 4 * gamma * cos(theta) / d
        self._p_capillary = (
            4.0 * self.config.surface_tension_water * math.cos(self.config.water_contact_angle)
        ) / self.config.tube_diameter

        # State variables
        self._time: float = 0.0
        self._water_level: float = 0.0  # Global water surface elevation (m)
        self._p_tube: float = self.config.p_atm - (self._r_air * self.config.suction_flow_rate)
        self._is_immersed: bool = False
        self._trip_triggered: bool = False
        self._water_column_fraction: float = 0.0  # Fraction of tube filled with water [0, 1]

    @property
    def r_air(self) -> float:
        """Hagen-Poiseuille viscous resistance for air (Pa*s/m^3)."""
        return self._r_air

    @property
    def r_water(self) -> float:
        """Hagen-Poiseuille viscous resistance for water (Pa*s/m^3)."""
        return self._r_water

    @property
    def p_tube(self) -> float:
        """Absolute internal sensing tube pressure (Pa absolute)."""
        return self._p_tube

    @property
    def gauge_pressure(self) -> float:
        """Relative tube pressure p_tube - p_atm (Pa gauge). Negative indicates vacuum."""
        return self._p_tube - self.config.p_atm

    @property
    def vacuum(self) -> float:
        """Magnitude of vacuum suction p_atm - p_tube (Pa)."""
        return max(0.0, self.config.p_atm - self._p_tube)

    @property
    def is_immersed(self) -> bool:
        """True if feeler tip altitude is below water surface level."""
        return self._is_immersed

    @property
    def trip_triggered(self) -> bool:
        """True if vacuum exceeded trip threshold (-25 kPa gauge) and commanded reversal."""
        return self._trip_triggered

    @property
    def capillary_pressure(self) -> float:
        """Capillary meniscus entry pressure (Pa)."""
        return self._p_capillary

    def tip_altitude(self, t: float | None = None) -> float:
        """Compute instantaneous feeler tip elevation with leg stride oscillation."""
        current_time = self._time if t is None else t
        return (
            self.base_altitude
            + self.config.oscillation_amplitude
            * math.sin(self.config.oscillation_frequency * current_time)
        )

    def set_water_level(self, z_water: float) -> None:
        """Set environmental water/tide elevation in meters."""
        self._water_level = z_water

    def reset_trip(self) -> None:
        """Reset the reflex trip status."""
        self._trip_triggered = False

    def step(
        self,
        dt: float,
        z_water: float | None = None,
        override_tip_altitude: float | None = None,
    ) -> bool:
        """Step feeler fluid dynamics and reflex state.

        Args:
            dt: Timestep (seconds).
            z_water: Optional new environmental water elevation (m).
            override_tip_altitude: Optional manual tip elevation (m).

        Returns:
            True if reverse trip reflex fired during this step.
        """
        if z_water is not None:
            self._water_level = z_water

        self._time += dt
        z_tip = (
            override_tip_altitude
            if override_tip_altitude is not None
            else self.tip_altitude(self._time)
        )

        # Check physical immersion: tip altitude at or below water elevation
        self._is_immersed = z_tip <= self._water_level

        vol = max(self._total_volume, 1e-9)

        if not self._is_immersed:
            # Tip in air: purge residual water slug and breathe free air
            self._water_column_fraction = max(0.0, self._water_column_fraction - 10.0 * dt)
            r_eff = self._r_air

            # In air: Hagen-Poiseuille equilibrium pressure p_target = p_atm - r_eff * q_suction
            p_target = self.config.p_atm - (r_eff * self.config.suction_flow_rate)
            tau = (vol * r_eff) / (self.config.gamma_air * max(self._p_tube, 1000.0))
            decay = math.exp(-dt / max(tau, 1e-6))
            self._p_tube = p_target + (self._p_tube - p_target) * decay

            # Bound: cannot exceed atmospheric in free aspiration
            if self._p_tube > self.config.p_atm:
                self._p_tube = self.config.p_atm
        else:
            # Tip in water: capillary entrance and high liquid viscosity (~55x air)
            # form a meniscus seal that blocks air ingestion into the narrow tube.
            self._water_column_fraction = min(1.0, self._water_column_fraction + 20.0 * dt)

            # Rapid evacuation under suction: dp/p = - (gamma / V) * q_suction * dt
            evac_rate = (self.config.gamma_air / vol) * self.config.suction_flow_rate
            self._p_tube *= math.exp(-evac_rate * dt)

            # Physical floor: absolute pressure cannot drop below zero
            if self._p_tube < 100.0:
                self._p_tube = 100.0

        # Reflex trip evaluation: gauge pressure drops below -25 kPa
        fired = False
        if self.gauge_pressure <= self.config.vacuum_trip_threshold:
            if not self._trip_triggered:
                self._trip_triggered = True
                fired = True
                self._trigger_reverse_reflex()

        return fired

    def _trigger_reverse_reflex(self) -> None:
        """Command the directional valve to reverse walking direction."""
        if self.valve is not None:
            # Control port B receives atmospheric while port A sees high vacuum
            # Differential pressure: p_B - p_A = p_atm - p_tube = vacuum > delta_p_switch
            p_A = self._p_tube
            p_B = self.config.p_atm
            self.valve.step(dt=0.01, p_A=p_A, p_B=p_B)
