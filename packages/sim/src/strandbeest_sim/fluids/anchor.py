"""Storm ground-anchor ("stormanker") stabilization reflex model.

Theo Jansen's storm anchor prevents capsizing during beach storms (wind > 15-20 m/s):
1. Tilt Detection:
   Monitors walker roll/pitch tilt angle theta = arccos(z_walker . z_up).
   If theta exceeds critical threshold theta_crit (18 deg = 0.314 rad) or
   sustained wind aerodynamic drag moment exceeds righting moment, the anchor fires.

2. Pneumatic Firing Mechanism:
   Shoots a steel anchor pin/spike (d = 12 mm, stroke = 0.15 m) into loose sand
   using high-pressure pneumatic cylinder (p_tank >= 400 kPa gauge).
   Dynamic equation of motion tracks spike acceleration, deployment velocity,
   and penetration depth.

3. Soil Mechanics Holding Force:
   Computes sand anchoring resistance using Rankine & Mohr-Coulomb passive earth
   pressure theory for a 3D embedded anchor in beach sand:
     sigma_p(z) = K_p * (gamma_sand * z + q_surcharge) + 2 * c * sqrt(K_p)
   where K_p = tan^2(45 deg + phi/2).
   Yields holding resistance force F_holding > 1500 N, securely anchoring
   the Strandbeest against gale-force shear and overturning moments.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass
class StormAnchorConfig:
    """Parameters for the storm anchor mechanism and soil mechanics.

    Attributes:
        theta_crit_deg: Critical walker tilt threshold in degrees (default 18.0 deg).
        spike_diameter: Diameter of steel anchor spike (m). Default 12 mm (0.012 m).
        stroke: Maximum extension/embedment depth into sand (m). Default 0.15 m (150 mm).
        spike_mass: Mass of sliding spike and piston rod (kg). Default 0.8 kg.
        piston_diameter: Actuation pneumatic cylinder bore diameter (m). Default 40 mm (0.04 m).
        p_tank: High-pressure pneumatic supply pressure (Pa absolute). Default 500 kPa.
        p_atm: Atmospheric pressure (Pa absolute). Default 101325 Pa.
        damping: Mechanical damping of piston during firing (N*s/m).
        phi_deg: Internal friction angle of beach sand in degrees (default 35.0 deg).
        gamma_sand: Unit weight of beach sand (N/m^3). Default 17000 N/m^3.
        c_cohesion: Apparent cohesion of damp coastal sand (Pa). Default 20000 Pa (20 kPa).
        q_surcharge: Surcharge pressure from anchor foot / walker weight (Pa). Default 15000 Pa.
        fluke_width: Effective width of anchor spade/fluke or 3D passive wedge (m). Default 0.10 m.
        walker_mass: Total walker mass (kg) for overturning moment comparison. Default 80 kg.
        stance_width: Walker track/stance width (m). Default 1.6 m.
        sail_center_height: Center of aerodynamic effort height (m). Default 1.4 m.
    """

    theta_crit_deg: float = 18.0  # 18 degrees
    spike_diameter: float = 0.012  # 12 mm
    stroke: float = 0.15  # 150 mm
    spike_mass: float = 0.8  # 0.8 kg
    piston_diameter: float = 0.04  # 40 mm
    p_tank: float = 500000.0  # 500 kPa abs
    p_atm: float = 101325.0  # Pa abs
    damping: float = 15.0  # N*s/m
    phi_deg: float = 35.0  # 35 deg sand internal friction
    gamma_sand: float = 17000.0  # 17 kN/m^3
    c_cohesion: float = 20000.0  # 20 kPa apparent cohesion
    q_surcharge: float = 15000.0  # 15 kPa foot contact surcharge
    fluke_width: float = 0.10  # 10 cm effective width
    walker_mass: float = 80.0  # kg
    stance_width: float = 1.6  # m
    sail_center_height: float = 1.4  # m


class StormAnchor:
    """Storm ground-anchor reflex mechanism."""

    def __init__(self, config: StormAnchorConfig | None = None) -> None:
        self.config = config or StormAnchorConfig()

        # Derived geometric values
        self._piston_area = math.pi * (self.config.piston_diameter / 2.0) ** 2
        self._spike_tip_area = math.pi * (self.config.spike_diameter / 2.0) ** 2
        self._theta_crit_rad = math.radians(self.config.theta_crit_deg)

        # Geotechnical Rankine passive earth pressure coefficient:
        # K_p = tan^2(45 deg + phi / 2) = (1 + sin phi) / (1 - sin phi)
        phi_rad = math.radians(self.config.phi_deg)
        sin_phi = math.sin(phi_rad)
        self._k_p = (1.0 + sin_phi) / (1.0 - sin_phi)
        self._sqrt_kp = math.sqrt(self._k_p)

        # State
        self._deployed: bool = False
        self._firing: bool = False
        self._penetration_depth: float = 0.0  # m (0 to stroke)
        self._velocity: float = 0.0  # m/s
        self._trigger_reason: str | None = None

    @property
    def k_p(self) -> float:
        """Rankine passive earth pressure coefficient."""
        return self._k_p

    @property
    def is_deployed(self) -> bool:
        """True if anchor spike has fully deployed into sand."""
        return self._deployed

    @property
    def is_firing(self) -> bool:
        """True while anchor spike is shooting downward."""
        return self._firing

    @property
    def penetration_depth(self) -> float:
        """Current spike penetration depth into sand (m)."""
        return self._penetration_depth

    @property
    def deployment_velocity(self) -> float:
        """Current spike deployment velocity (m/s)."""
        return self._velocity

    @property
    def theta_crit_rad(self) -> float:
        """Critical tilt threshold in radians."""
        return self._theta_crit_rad

    @property
    def trigger_reason(self) -> str | None:
        """Reason why anchor was triggered, if triggered."""
        return self._trigger_reason

    def compute_tilt_angle(self, z_walker: Sequence[float]) -> float:
        """Compute walker roll/pitch tilt angle relative to vertical.

        Args:
            z_walker: 3D vector representing walker's local up-axis [zx, zy, zz].

        Returns:
            Tilt angle theta in radians in [0, pi].
        """
        norm = math.sqrt(z_walker[0] ** 2 + z_walker[1] ** 2 + z_walker[2] ** 2)
        if norm <= 1e-9:
            return 0.0
        # Global up is [0, 0, 1]
        cos_theta = z_walker[2] / norm
        cos_theta = max(-1.0, min(1.0, cos_theta))
        return math.acos(cos_theta)

    def check_tilt_trigger(self, z_walker: Sequence[float]) -> bool:
        """Evaluate if walker tilt angle exceeds theta_crit."""
        theta = self.compute_tilt_angle(z_walker)
        return theta >= self._theta_crit_rad

    def check_wind_overturn(self, wind_drag_force: float) -> bool:
        """Evaluate if sustained wind drag causes imminent tip-over.

        Righting moment: M_restore = walker_mass * g * (stance_width / 2)
        Overturning moment: M_drag = wind_drag_force * sail_center_height
        """
        g = 9.81
        m_restore = self.config.walker_mass * g * (self.config.stance_width / 2.0)
        m_drag = abs(wind_drag_force) * self.config.sail_center_height
        return m_drag >= m_restore

    def trigger(self, reason: str = "manual") -> None:
        """Trigger deployment of storm anchor."""
        if not self._deployed and not self._firing:
            self._firing = True
            self._trigger_reason = reason

    def passive_earth_pressure(self, depth: float) -> float:
        """Compute Mohr-Coulomb passive earth pressure at given depth (Pa).

        sigma_p(z) = K_p * (gamma_sand * z + q_surcharge) + 2 * c * sqrt(K_p)
        """
        effective_vertical_stress = self.config.gamma_sand * depth + self.config.q_surcharge
        cohesion_term = 2.0 * self.config.c_cohesion * self._sqrt_kp
        return self._k_p * effective_vertical_stress + cohesion_term

    def compute_holding_force(self, depth: float | None = None) -> float:
        """Compute sand anchoring holding resistance force F_holding (N).

        Uses Rankine / Mohr-Coulomb passive wedge integration over the embedment depth L:
          F_shear = integral_0^L sigma_p(z) * B_eff(z) dz
        where:
          B_eff(z) = max(fluke_width, spike_diameter + 2 * z * tan(phi))
          sigma_p(z) = K_p * (gamma * z + q) + 2 * c * sqrt(K_p)
        """
        l_embed = self.config.stroke if depth is None else depth
        if l_embed <= 0.0:
            return 0.0

        # Numerical integration using Simpson's rule across depth
        n_steps = 20
        dz = l_embed / n_steps
        tan_phi = math.tan(math.radians(self.config.phi_deg))

        total_force = 0.0
        for i in range(n_steps + 1):
            z = i * dz
            b_eff = max(
                self.config.fluke_width,
                self.config.spike_diameter + 2.0 * z * tan_phi,
            )
            p_passive = self.passive_earth_pressure(z)
            d_force = p_passive * b_eff

            weight = 1.0 if (i == 0 or i == n_steps) else (4.0 if i % 2 == 1 else 2.0)
            total_force += weight * d_force

        f_shear = total_force * (dz / 3.0)
        return f_shear

    def sand_penetration_resistance(self, depth: float) -> float:
        """Estimate dynamic penetration resistance force opposing spike driving (N).

        Based on dynamic cone penetrometer / Meyerhof bearing capacity:
          q_c = gamma * depth * N_q + c * N_c
        """
        phi_rad = math.radians(self.config.phi_deg)
        # Meyerhof bearing capacity factor N_q
        n_q = math.exp(math.pi * math.tan(phi_rad)) * self._k_p
        sigma_v = self.config.gamma_sand * depth
        q_c = sigma_v * n_q + self.config.c_cohesion * 20.0
        f_tip = q_c * self._spike_tip_area
        f_skin = (
            math.pi
            * self.config.spike_diameter
            * depth
            * (0.5 * sigma_v * math.tan(phi_rad) + 0.3 * self.config.c_cohesion)
        )
        return f_tip + f_skin

    def step(
        self,
        dt: float,
        z_walker: Sequence[float] | None = None,
        wind_drag_force: float | None = None,
    ) -> bool:
        """Step storm anchor reflex state and deployment physics.

        Args:
            dt: Timestep (seconds).
            z_walker: Optional walker torso up-vector [zx, zy, zz].
            wind_drag_force: Optional instantaneous aerodynamic drag force (N).

        Returns:
            True if anchor is fully deployed and holding.
        """
        # Sensor check if not already firing or deployed
        if not self._firing and not self._deployed:
            if z_walker is not None and self.check_tilt_trigger(z_walker):
                self.trigger(reason="critical_tilt")
            elif wind_drag_force is not None and self.check_wind_overturn(wind_drag_force):
                self.trigger(reason="wind_overturn_imminent")

        # Firing dynamics
        if self._firing:
            # Pneumatic drive force: F_drive = (p_tank - p_atm) * A_piston
            f_drive = (self.config.p_tank - self.config.p_atm) * self._piston_area
            # Opposing penetration resistance
            f_res = self.sand_penetration_resistance(self._penetration_depth)
            f_damp = self.config.damping * self._velocity

            f_net = f_drive - f_res - f_damp
            accel = f_net / self.config.spike_mass

            self._velocity = max(0.0, self._velocity + accel * dt)
            self._penetration_depth += self._velocity * dt

            # Check full stroke
            if self._penetration_depth >= self.config.stroke:
                self._penetration_depth = self.config.stroke
                self._velocity = 0.0
                self._firing = False
                self._deployed = True

        return self._deployed
