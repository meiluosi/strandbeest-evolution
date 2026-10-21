"""Wind velocity models for wind-driven walker simulation (WIND.md, W-04).

Provides:
  - constant: steady horizontal wind
  - gusts: sinusoidal gust envelope
  - lull: steady wind dropping to zero after a specified duration
  - turbulent: stationary Gaussian stochastic turbulence (Dryden / Ornstein-Uhlenbeck process)
  - shear: atmospheric boundary layer vertical shear profile (power-law or logarithmic)
  - profile_turbulent: combined boundary layer profile, stochastic turbulence, and yaw angle
"""

from __future__ import annotations

import math
import random
from typing import Callable, Optional

from .config import Wind
from .registry import winds

# Wind function protocol: f(t, z=None) -> float
WindFn = Callable[[float, Optional[float]], float]


def _shear_factor(
    z: float | None,
    z_ref: float,
    alpha: float,
    z_0: float,
    profile: str,
    min_ratio: float,
) -> float:
    """Calculate the atmospheric boundary layer wind speed scaling factor at height z."""
    if z is None:
        return 1.0
    z_safe = max(z, 1e-4)
    if profile == "log":
        # Logarithmic wind profile: ln(z/z_0) / ln(z_ref/z_0)
        num = max(0.0, math.log(max(z_safe, z_0) / z_0))
        denom = max(1e-4, math.log(max(z_ref, z_0) / z_0))
        return max(min_ratio, num / denom)
    else:
        # Power-law wind profile: (z / z_ref)^alpha
        return max(min_ratio, (z_safe / z_ref) ** alpha)


class TurbulentGenerator:
    """Stationary Gauss-Markov stochastic turbulence generator (Dryden / Ornstein-Uhlenbeck process).

    Generates velocity fluctuations u'(t) with zero mean, standard deviation sigma_u = I_u * v_mean,
    and exponential autocorrelation R(dt) = exp(-dt / tau_u), where tau_u = L_u / v_mean.
    """

    def __init__(
        self,
        mean_speed: float,
        intensity: float = 0.15,
        integral_length: float = 25.0,
        seed: int = 1,
        dt: float = 0.05,
        yaw_deg: float = 0.0,
    ) -> None:
        self.mean_speed = mean_speed
        self.intensity = intensity
        self.integral_length = integral_length
        self.seed = seed
        self.dt = dt
        self.yaw_deg = yaw_deg
        self.cos_yaw = max(0.0, math.cos(math.radians(yaw_deg)))

        self.tau = integral_length / max(mean_speed, 0.1)
        self.sigma = intensity * mean_speed
        self.decay = math.exp(-dt / self.tau)
        self.noise_scale = self.sigma * math.sqrt(max(0.0, 1.0 - math.exp(-2.0 * dt / self.tau)))

        self.rng = random.Random(seed)
        # Initial fluctuation drawn from the stationary distribution N(0, sigma^2)
        u0 = self.rng.gauss(0.0, self.sigma)
        self.buffer = [u0]

    def _extend_to(self, target_idx: int) -> None:
        u = self.buffer[-1]
        while len(self.buffer) <= target_idx:
            u = u * self.decay + self.rng.gauss(0.0, self.noise_scale)
            self.buffer.append(u)

    def get_fluctuation(self, t: float) -> float:
        if t <= 0.0:
            return self.buffer[0]
        idx = int(t / self.dt)
        alpha = (t - idx * self.dt) / self.dt
        self._extend_to(idx + 1)
        return (1.0 - alpha) * self.buffer[idx] + alpha * self.buffer[idx + 1]

    def __call__(self, t: float, z: float | None = None) -> float:
        u_t = self.get_fluctuation(t)
        total_v = max(0.0, self.mean_speed + u_t)
        return total_v * self.cos_yaw


@winds.register("constant")
def constant(w: Wind) -> WindFn:
    yaw_deg = float(w.params.get("yaw_deg", 0.0))
    cos_yaw = max(0.0, math.cos(math.radians(yaw_deg)))
    speed = w.speed * cos_yaw
    return lambda t, z=None: speed


@winds.register("gusts")
def gusts(w: Wind) -> WindFn:
    """Mean speed plus a sinusoidal gust: params amplitude (m/s) and period (s). Never negative."""
    amp = float(w.params.get("amplitude", 1.0))
    period = float(w.params.get("period", 6.0))
    yaw_deg = float(w.params.get("yaw_deg", 0.0))
    cos_yaw = max(0.0, math.cos(math.radians(yaw_deg)))
    return lambda t, z=None: max(0.0, (w.speed + amp * math.sin(2 * math.pi * t / period)) * cos_yaw)


@winds.register("lull")
def lull(w: Wind) -> WindFn:
    """Steady wind that drops to zero at `at` seconds (tests how far a walker coasts)."""
    at = float(w.params.get("at", 10.0))
    yaw_deg = float(w.params.get("yaw_deg", 0.0))
    cos_yaw = max(0.0, math.cos(math.radians(yaw_deg)))
    speed = w.speed * cos_yaw
    return lambda t, z=None: speed if t < at else 0.0


@winds.register("turbulent")
def turbulent(w: Wind) -> WindFn:
    """Stationary Gaussian stochastic turbulence (Dryden / Ornstein-Uhlenbeck process)."""
    intensity = float(w.params.get("intensity", 0.15))
    integral_length = float(w.params.get("integral_length", 25.0))
    seed = int(w.params.get("seed", 1))
    dt = float(w.params.get("dt", 0.05))
    yaw_deg = float(w.params.get("yaw_deg", 0.0))
    gen = TurbulentGenerator(w.speed, intensity, integral_length, seed, dt, yaw_deg)
    return gen


@winds.register("shear")
def shear(w: Wind) -> WindFn:
    """Atmospheric boundary layer vertical wind shear profile with height z."""
    z_ref = float(w.params.get("z_ref", 1.0))
    alpha = float(w.params.get("alpha", 0.14))
    z_0 = float(w.params.get("z_0", 0.0002))
    profile = str(w.params.get("profile", "power"))
    min_ratio = float(w.params.get("min_speed_ratio", 0.05))
    yaw_deg = float(w.params.get("yaw_deg", 0.0))
    cos_yaw = max(0.0, math.cos(math.radians(yaw_deg)))

    def fn(t: float, z: float | None = None) -> float:
        sf = _shear_factor(z, z_ref, alpha, z_0, profile, min_ratio)
        return max(0.0, w.speed * sf * cos_yaw)

    return fn


@winds.register("profile_turbulent")
def profile_turbulent(w: Wind) -> WindFn:
    """Combined boundary layer vertical wind profile, stochastic turbulence, and yaw angle."""
    z_ref = float(w.params.get("z_ref", 1.0))
    alpha = float(w.params.get("alpha", 0.14))
    z_0 = float(w.params.get("z_0", 0.0002))
    profile = str(w.params.get("profile", "power"))
    min_ratio = float(w.params.get("min_speed_ratio", 0.05))

    intensity = float(w.params.get("intensity", 0.15))
    integral_length = float(w.params.get("integral_length", 25.0))
    seed = int(w.params.get("seed", 1))
    dt = float(w.params.get("dt", 0.05))
    yaw_deg = float(w.params.get("yaw_deg", 0.0))
    cos_yaw = max(0.0, math.cos(math.radians(yaw_deg)))

    turb = TurbulentGenerator(w.speed, intensity, integral_length, seed, dt, yaw_deg=0.0)

    def fn(t: float, z: float | None = None) -> float:
        sf = _shear_factor(z, z_ref, alpha, z_0, profile, min_ratio)
        u_t = turb.get_fluctuation(t)
        base_v = max(0.0, w.speed * sf + u_t)
        return base_v * cos_yaw

    return fn
