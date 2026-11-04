"""Dynamic coastal tide water elevation model for the Digital Beach sandbox.

Theo Jansen walkers forage on coastal tidal beaches (e.g. Scheveningen beach in the Netherlands).
Tidal water levels vary dynamically with coastal gravity waves and astronomical tides:
    z_water(t) = z0 + h_tide * sin(omega_tide * t)
where:
    z0: mean sea / tide water elevation (m)
    h_tide: tidal amplitude (m)
    omega_tide: tidal angular frequency (rad/s)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class DynamicTideField:
    """Dynamic coastal tide water elevation model:
    z_water(t) = z0 + h_tide * sin(omega_tide * t).

    Attributes:
        z0: Mean water elevation relative to beach ground datum (m). Default 0.0 m.
        h_tide: Tidal wave amplitude (m). Default 0.15 m.
        omega_tide: Tidal angular frequency (rad/s). Default 0.5 rad/s.
    """

    z0: float = 0.0
    h_tide: float = 0.15
    omega_tide: float = 0.5

    def water_level(self, t: float) -> float:
        """Evaluate water elevation at time t in meters."""
        return self.z0 + self.h_tide * math.sin(self.omega_tide * t)

    def is_submerged(self, z_tip: float, t: float) -> bool:
        """Check whether tip altitude is at or below the instantaneous tide level."""
        return z_tip <= self.water_level(t)

    def submergence_depth(self, z_tip: float, t: float) -> float:
        """Depth of submergence below water surface in meters (0 if in air)."""
        return max(0.0, self.water_level(t) - z_tip)

    def __call__(self, t: float) -> float:
        return self.water_level(t)
