import mujoco

from .config import Scenario
from .registry import terrains


@terrains.register("flat")
def flat(sc: Scenario, model: mujoco.MjModel) -> None:
    """Level rigid ground; friction comes from the scenario."""


@terrains.register("slope")
def slope(sc: Scenario, model: mujoco.MjModel) -> None:
    """Rigid incline, modelled by tilting gravity in the slope frame (uphill = +x)."""
    a = sc.terrain.slope_deg * 3.141592653589793 / 180
    model.opt.gravity[:] = (-9.81 * __import__("math").sin(a), 0.0, -9.81 * __import__("math").cos(a))
