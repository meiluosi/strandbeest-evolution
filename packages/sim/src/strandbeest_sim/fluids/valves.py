"""Bistable mechanical detent slide valve (Flip-Flop) for Strandbeest pneumatic logic.

Theo Jansen's pneumatic brain uses mechanical detent slide valves as fluidic flip-flops.
A slide spool shuttles between two stable positions:
  - State S = +1 (Forward): Supply connects to Forward channel, Reverse channel exhausts.
  - State S = -1 (Reverse): Supply connects to Reverse channel, Forward channel exhausts.

Switching dynamics:
  Mechanical detent spring holds the spool in place against control pressures until
  the differential pressure |p_A - p_B| exceeds the detent threshold delta_p_switch.
  Inside the deadband |p_A - p_B| <= delta_p_switch, the valve remains latched (hysteresis).
  When (p_A - p_B) > delta_p_switch, it snaps to S = +1.
  When (p_B - p_A) > delta_p_switch (i.e. p_A - p_B < -delta_p_switch), it snaps to S = -1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


@dataclass
class BistableValveConfig:
    """Configuration for a bistable mechanical detent slide valve.

    Attributes:
        delta_p_switch: Differential pressure threshold required to trip detent (Pa).
        spool_mass: Mass of sliding spool assembly (kg).
        spool_stroke: Total travel stroke between -1 and +1 positions (m).
        spool_area: Effective cross-sectional area of control piston faces (m^2).
        p_supply: Standard nominal supply pressure (Pa absolute).
        p_exhaust: Atmospheric exhaust pressure (Pa absolute).
        c_viscous: Viscous damping coefficient on spool motion (N*s/m).
        flow_conductance: Pneumatic port conductance C (m^3/(s*Pa)).
    """

    delta_p_switch: float = 15000.0  # 15 kPa
    spool_mass: float = 0.02  # 20 g spool
    spool_stroke: float = 0.01  # 10 mm stroke (-5 mm to +5 mm)
    spool_area: float = 1.0e-4  # 1 cm^2 piston area
    p_supply: float = 300000.0  # 300 kPa (3 bar abs)
    p_exhaust: float = 101325.0  # 1 atm abs
    c_viscous: float = 2.0  # N*s/m damping
    flow_conductance: float = 5.0e-7  # m^3/(s*Pa)


class BistableValve:
    """Bistable slide valve with mechanical detent spring hysteresis."""

    def __init__(
        self,
        config: BistableValveConfig | None = None,
        initial_state: Literal[-1, 1] = 1,
    ) -> None:
        self.config = config or BistableValveConfig()
        if initial_state not in (-1, 1):
            raise ValueError(f"initial_state must be -1 or +1, got {initial_state}")

        self._state: Literal[-1, 1] = initial_state
        self._half_stroke = self.config.spool_stroke / 2.0
        # Continuous state: position x (m) in [-half_stroke, +half_stroke], velocity v (m/s)
        self._x: float = self._half_stroke if initial_state == 1 else -self._half_stroke
        self._v: float = 0.0

        # Port pressures
        self._p_supply: float = self.config.p_supply
        self._p_exhaust: float = self.config.p_exhaust
        self._p_forward: float = self.config.p_supply if initial_state == 1 else self.config.p_exhaust
        self._p_reverse: float = self.config.p_exhaust if initial_state == 1 else self.config.p_supply

    @property
    def state(self) -> Literal[-1, 1]:
        """Current discrete latch state: +1 for Forward, -1 for Reverse."""
        return self._state

    @property
    def is_forward(self) -> bool:
        """True if routed to forward channel."""
        return self._state == 1

    @property
    def is_reverse(self) -> bool:
        """True if routed to reverse channel."""
        return self._state == -1

    @property
    def spool_position(self) -> float:
        """Continuous spool position in meters relative to mid-stroke."""
        return self._x

    @property
    def spool_velocity(self) -> float:
        """Continuous spool velocity in m/s."""
        return self._v

    @property
    def p_forward(self) -> float:
        """Absolute pressure delivered to forward drive channel (Pa)."""
        return self._p_forward

    @property
    def p_reverse(self) -> float:
        """Absolute pressure delivered to reverse drive channel (Pa)."""
        return self._p_reverse

    @property
    def delta_p_switch(self) -> float:
        """Detent switching differential pressure threshold (Pa)."""
        return self.config.delta_p_switch

    def detent_force(self, x: float) -> float:
        """Compute mechanical detent spring force at spool displacement x.

        Modeled as a bistable double-well potential holding force:
          Peak force occurs at x = half_stroke / sqrt(3).
          F_detent = (3 * sqrt(3) / 2) * F_peak * (x / x_0) * (1 - (x / x_0)^2)
        For x in (0, x_0), F_detent > 0 (restoring towards +x_0).
        For x in (-x_0, 0), F_detent < 0 (restoring towards -x_0).
        The maximum holding force matches delta_p_switch * A_spool.
        """
        x_0 = max(self._half_stroke, 1e-6)
        s = max(-1.0, min(1.0, x / x_0))
        f_peak = self.config.delta_p_switch * self.config.spool_area
        c = (3.0 * math.sqrt(3.0) / 2.0) * f_peak
        return c * s * (1.0 - s * s)

    def evaluate_switching(self, p_A: float, p_B: float) -> Literal[-1, 0, 1]:
        """Evaluate discrete threshold switching logic without stepping time.

        Returns:
            +1 if switched to forward, -1 if switched to reverse, 0 if no change.
        """
        dp = p_A - p_B
        thresh = self.config.delta_p_switch

        if dp > thresh and self._state != 1:
            self._state = 1
            self._x = self._half_stroke
            self._v = 0.0
            self._update_port_pressures()
            return 1
        elif -dp > thresh and self._state != -1:
            self._state = -1
            self._x = -self._half_stroke
            self._v = 0.0
            self._update_port_pressures()
            return -1

        return 0

    def switch_to(self, target_state: Literal[-1, 1]) -> None:
        """Forced programmatic switch (e.g. from an override or trip trigger)."""
        if target_state not in (-1, 1):
            raise ValueError(f"target_state must be -1 or +1, got {target_state}")
        self._state = target_state
        self._x = self._half_stroke if target_state == 1 else -self._half_stroke
        self._v = 0.0
        self._update_port_pressures()

    def step(
        self,
        dt: float,
        p_A: float,
        p_B: float,
        p_supply: float | None = None,
        p_exhaust: float | None = None,
    ) -> Literal[-1, 1]:
        """Advance valve dynamics over timestep dt under control pressures p_A and p_B.

        Args:
            dt: Timestep (seconds).
            p_A: Absolute control pressure at port A (Pa).
            p_B: Absolute control pressure at port B (Pa).
            p_supply: Optional updated supply pressure (Pa absolute).
            p_exhaust: Optional updated exhaust pressure (Pa absolute).

        Returns:
            Current discrete state (+1 or -1).
        """
        if p_supply is not None:
            self._p_supply = p_supply
        if p_exhaust is not None:
            self._p_exhaust = p_exhaust

        if dt <= 0.0:
            self.evaluate_switching(p_A, p_B)
            return self._state

        # Differential pressure force on spool
        dp = p_A - p_B
        f_pressure = dp * self.config.spool_area

        # Detent force
        f_det = self.detent_force(self._x)

        # Viscous damping
        f_damp = -self.config.c_viscous * self._v

        # Acceleration
        f_net = f_pressure + f_det + f_damp
        a = f_net / self.config.spool_mass

        # Semi-implicit Euler integration
        self._v += a * dt
        self._x += self._v * dt

        # Mechanical stroke limits
        if self._x >= self._half_stroke:
            self._x = self._half_stroke
            if self._v > 0:
                self._v = 0.0
        elif self._x <= -self._half_stroke:
            self._x = -self._half_stroke
            if self._v < 0:
                self._v = 0.0

        # Update discrete state based on position and detent threshold
        # Hysteresis switching:
        if self._state == -1 and dp > self.config.delta_p_switch and self._x > 0:
            self._state = 1
        elif self._state == 1 and -dp > self.config.delta_p_switch and self._x < 0:
            self._state = -1
        elif dp > self.config.delta_p_switch:
            self._state = 1
        elif -dp > self.config.delta_p_switch:
            self._state = -1

        self._update_port_pressures()
        return self._state

    def _update_port_pressures(self) -> None:
        """Route supply and exhaust to forward/reverse channels according to spool state."""
        if self._state == 1:
            self._p_forward = self._p_supply
            self._p_reverse = self._p_exhaust
        else:
            self._p_forward = self._p_exhaust
            self._p_reverse = self._p_supply
