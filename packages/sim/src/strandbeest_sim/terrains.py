import math
import random

import mujoco

from .config import SimConfig
from .registry import terrain_xml, terrains

OBSTACLE = 'type="box" contype="1" conaffinity="2" rgba="0.62 0.58 0.5 1"'


def _fric(sc: SimConfig) -> str:
    return f'friction="{sc.terrain.friction} 0.005 0.0001"'


# ---- post-compile hooks (change model options) ----
@terrains.register("flat")
def flat(sc: SimConfig, model: mujoco.MjModel) -> None:
    """Level rigid ground; friction comes from the scenario."""


@terrains.register("slope")
def slope(sc: SimConfig, model: mujoco.MjModel) -> None:
    """Rigid incline, modelled by tilting gravity in the slope frame (uphill = +x)."""
    a = math.radians(sc.terrain.slope_deg)
    g = sc.environment.gravity
    model.opt.gravity[:] = (-g * math.sin(a), 0.0, -g * math.cos(a))


@terrains.register("step")
def step(sc: SimConfig, model: mujoco.MjModel) -> None:
    """A single raised block the feet must climb (geometry from terrain_xml)."""


@terrains.register("bumps")
def bumps(sc: SimConfig, model: mujoco.MjModel) -> None:
    """Randomly placed raised blocks (geometry from terrain_xml)."""


@terrains.register("soft")
def soft(sc: SimConfig, model: mujoco.MjModel) -> None:
    """Crude soft ground: much softer, more damped foot contact. NOT a model of sand (no sinkage, no granular flow).

    For two geoms in contact with direct (negative) solref MuJoCo uses the STIFFER one, so the softness must be set on both the
    terrain geoms (body 0) and the feet. Until 2026-10-06 it was set on the feet only, where the stiff ground always won: "soft"
    ground behaved exactly like flat ground (found while recording golden runs; the result is in docs/EXPERIMENTS.md)."""
    solref = (-float(sc.terrain.params.get("stiffness", 4000.0)), -float(sc.terrain.params.get("damping", 120.0)))
    for i in range(model.ngeom):
        if model.geom_bodyid[i] == 0 or model.geom_contype[i] == 2:
            model.geom_solref[i] = solref
# ---- geometry added to the world at compile time ----
@terrain_xml.register("flat")
@terrain_xml.register("slope")
@terrain_xml.register("soft")
def none(sc: SimConfig) -> str:
    return ""


@terrain_xml.register("step")
def step_xml(sc: SimConfig) -> str:
    p = sc.terrain.params
    d, h, length = float(p.get("distance", 0.5)), float(p.get("height", 0.02)), float(p.get("length", 1.0))
    return f'<geom name="step" {OBSTACLE} {_fric(sc)} pos="{d + length / 2} 0 {h / 2}" size="{length / 2} 5 {h / 2}"/>'


@terrain_xml.register("bumps")
def bumps_xml(sc: SimConfig) -> str:
    p = sc.terrain.params
    rng = random.Random(int(p.get("seed", 1)))
    n, hmax = int(p.get("count", 12)), float(p.get("max_height", 0.015))
    x, out = float(p.get("start", 0.4)), []
    for i in range(n):
        w, h = rng.uniform(0.04, 0.12), rng.uniform(0.2, 1.0) * hmax
        out.append(f'<geom name="bump{i}" {OBSTACLE} {_fric(sc)} pos="{x + w / 2} 0 {h / 2}" size="{w / 2} 5 {h / 2}"/>')
        x += w + rng.uniform(0.05, 0.3)
    return "".join(out)
