"""Scenes, the sail drive, replay frames and the foot-collision fix."""

import mujoco
import numpy as np
import pytest

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.runner import make_sim

DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
FAST = {"run": {"revolutions": 0.6, "settle": 0.3}}


def sc(**ov):
    out = {k: dict(v) for k, v in FAST.items()}
    for k, v in ov.items():
        out.setdefault(k, {}).update(v)
    return scenario_from_design(DESIGN, out)


def test_each_leg_has_one_foot_sphere_and_feet_never_collide_with_each_other():
    sim = make_sim(sc())
    m = sim.model
    feet = [g for g in range(m.ngeom) if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "").startswith("foot_")]
    assert len(feet) == DESIGN.walker["legs"]
    for a in feet:
        for b in feet:
            assert not ((m.geom_contype[a] & m.geom_conaffinity[b]) or (m.geom_contype[b] & m.geom_conaffinity[a]))
    ground = next(g for g in range(m.ngeom) if mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) == "ground")
    assert m.geom_contype[feet[0]] & m.geom_conaffinity[ground]  # feet do hit the terrain


def test_recorded_frames_cover_every_body_and_feet_actually_leave_the_ground():
    r = run(sc(run={"revolutions": 1.0}))
    f = r.frames
    assert f["pos"].shape[1] == len(r.scene["bodies"]) and f["quat"].shape[2] == 4
    down = f["contact"].sum(axis=1)
    assert down.min() < DESIGN.walker["legs"] and down.max() >= 2  # swing legs exist, some feet always support
    assert r.metrics["max_penetration"] < 0.003  # feet sink under 3 mm at the default stiffness


def test_sail_drive_starts_in_a_fresh_wind_and_not_in_a_dead_calm():
    base = {"drive": {"kind": "sail"}, "run": {"revolutions": 0.5, "settle": 0.3, "give_up_after": 5, "max_time": 20, "frame_rate": 0}}
    windy = run(sc(**base, wind={"speed": 3.0}))
    calm = run(sc(**base, wind={"speed": 0.0}))
    assert not windy.stalled and windy.x[-1] - windy.x[0] > 0.1
    assert calm.stalled and calm.x[-1] - calm.x[0] < 0.01


def test_denser_air_drives_the_same_sail_harder():
    kw = {"drive": {"kind": "sail"}, "wind": {"speed": 1.0}, "run": {"revolutions": 0.5, "settle": 0.3, "give_up_after": 8, "max_time": 30, "frame_rate": 0}}
    thin = run(sc(**kw, environment={"air_density": 0.2}))
    thick = run(sc(**kw, environment={"air_density": 5.0}))
    assert thick.t[-1] < thin.t[-1] or thin.stalled


def test_terrain_geometry_and_gravity_come_from_the_scenario():
    step = make_sim(sc(terrain={"kind": "step", "params": {"distance": 0.2, "height": 0.01}}))
    assert any((mujoco.mj_id2name(step.model, mujoco.mjtObj.mjOBJ_GEOM, g) or "") == "step" for g in range(step.model.ngeom))
    bumps = make_sim(sc(terrain={"kind": "bumps", "params": {"count": 5, "seed": 2}}))
    assert sum((mujoco.mj_id2name(bumps.model, mujoco.mjtObj.mjOBJ_GEOM, g) or "").startswith("bump") for g in range(bumps.model.ngeom)) == 5
    moon = make_sim(sc(environment={"gravity": 1.62}))
    assert moon.model.opt.gravity[2] == pytest.approx(-1.62)
    slope = make_sim(sc(terrain={"kind": "slope", "slope_deg": 10}))
    assert slope.model.opt.gravity[0] < 0 and np.linalg.norm(slope.model.opt.gravity) == pytest.approx(9.81)


def test_a_blocked_walker_is_stopped_by_the_motor_torque_limit_instead_of_blowing_up():
    r = run(sc(terrain={"kind": "step", "params": {"distance": 0.1, "height": 0.03}}, run={"revolutions": 1.5, "frame_rate": 0}))
    assert np.isfinite(r.x).all() and abs(r.x).max() < 5.0


def test_mean_torque_does_not_depend_on_how_many_revolutions_were_run():
    """The mean is taken over whole revolutions after the first, so run length must not bias it."""
    a = run(sc(run={"revolutions": 2.0, "frame_rate": 0})).metrics
    b = run(sc(run={"revolutions": 3.0, "frame_rate": 0})).metrics
    assert a["steady_window"] == 1.0 and b["steady_window"] == 1.0
    assert a["mean_torque"] == pytest.approx(b["mean_torque"], rel=0.05)
    short = run(sc(run={"revolutions": 1.2, "frame_rate": 0})).metrics
    assert short["steady_window"] == 0.0  # shorter runs are marked: their means include the start-up
