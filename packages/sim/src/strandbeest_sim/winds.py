import math

from .config import Wind
from .registry import winds


@winds.register("constant")
def constant(w: Wind):
    return lambda t: w.speed


@winds.register("gusts")
def gusts(w: Wind):
    """Mean speed plus a sinusoidal gust: params amplitude (m/s) and period (s). Never negative."""
    amp = float(w.params.get("amplitude", 1.0))
    period = float(w.params.get("period", 6.0))
    return lambda t: max(0.0, w.speed + amp * math.sin(2 * math.pi * t / period))


@winds.register("lull")
def lull(w: Wind):
    """Steady wind that drops to zero at `at` seconds (tests how far a walker coasts)."""
    at = float(w.params.get("at", 10.0))
    return lambda t: w.speed if t < at else 0.0
