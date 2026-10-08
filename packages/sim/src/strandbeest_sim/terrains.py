"""Terrains as backend-neutral plans: which blocks stand on the ground, how steep it is, how soft. A physics backend turns a
plan into its own geometry and options (see backend.TerrainPlan)."""

import math
import random

from .backend import Box, TerrainPlan
from .config import SimConfig
from .registry import terrains


@terrains.register("flat")
def flat(sc: SimConfig) -> TerrainPlan:
    """Level rigid ground; friction comes from the scenario."""
    return TerrainPlan()


@terrains.register("slope")
def slope(sc: SimConfig) -> TerrainPlan:
    """Rigid incline, modelled by tilting gravity in the slope frame (uphill = +x)."""
    return TerrainPlan(slope_deg=sc.terrain.slope_deg)


@terrains.register("step")
def step(sc: SimConfig) -> TerrainPlan:
    """A single raised block the feet must climb."""
    p = sc.terrain.params
    d, h, length = float(p.get("distance", 0.5)), float(p.get("height", 0.02)), float(p.get("length", 1.0))
    return TerrainPlan(obstacles=(Box("step", (d + length / 2, 0, h / 2), (length / 2, 5, h / 2), sc.terrain.friction),))


@terrains.register("bumps")
def bumps(sc: SimConfig) -> TerrainPlan:
    """Randomly placed raised blocks."""
    p = sc.terrain.params
    rng = random.Random(int(p.get("seed", 1)))
    n, hmax = int(p.get("count", 12)), float(p.get("max_height", 0.015))
    x, out = float(p.get("start", 0.4)), []
    for i in range(n):
        w, h = rng.uniform(0.04, 0.12), rng.uniform(0.2, 1.0) * hmax
        out.append(Box(f"bump{i}", (x + w / 2, 0, h / 2), (w / 2, 5, h / 2), sc.terrain.friction))
        x += w + rng.uniform(0.05, 0.3)
    return TerrainPlan(obstacles=tuple(out))


@terrains.register("soft")
def soft(sc: SimConfig) -> TerrainPlan:
    """Crude soft ground: much softer, more damped contact. NOT a model of sand (no sinkage, no granular flow).

    The softness must apply to both the terrain and the feet: for two geoms with direct solref MuJoCo uses the stiffer one
    (until 2026-10-06 only the feet were softened and "soft" ground behaved exactly like flat ground; docs/EXPERIMENTS.md section 13)."""
    return TerrainPlan(softness=(float(sc.terrain.params.get("stiffness", 4000.0)), float(sc.terrain.params.get("damping", 120.0))))
