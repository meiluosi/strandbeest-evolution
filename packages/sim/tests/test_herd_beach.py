"""Tests for Digital Beach multi-walker sandbox and herd dynamics (M8-03).

Acceptance criteria:
- Real multi-body dynamics co-simulating multiple walkers in a shared physical world.
- Spatiotemporal wind field: v_wind(t, x, y) = v0 + A * sin(omega * t + kx * x).
- Dynamic tide water level: z_water(t) = z0 + h_tide * sin(omega_tide * t).
- Mutual bumper collisions and repulsive bumper forces separating walkers.
- Autonomous morphological reflexes:
  * Water feeler trips direction reversal when submerged by rising tide.
  * Storm anchor deploys and anchors into beach sand when tilted by pushing.
"""

import copy
import math
import numpy as np
import pytest

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import (
    DynamicTideField,
    HerdResult,
    SpatiotemporalWindField,
    build_herd,
    run_herd,
    scenario_from_design,
)
from strandbeest_sim.fluids import BistableValve, StormAnchor, StormAnchorConfig, WaterFeeler

DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")


def _make_herd_scenario(walker_configs: list[dict]) -> dict:
    """Helper to build a multi-walker scenario doc from small-6leg design template."""
    sc_solo = scenario_from_design(DESIGN)
    ent_template = sc_solo.entities[0].model_dump(mode="json")

    entities = []
    for cfg in walker_configs:
        ent = copy.deepcopy(ent_template)
        ent["name"] = cfg["name"]
        ent["placement"] = {
            "x": cfg.get("x", 0.0),
            "y": cfg.get("y", 0.0),
            "phase_offset": cfg.get("phase_offset", 0.0),
        }
        if "pitch" in cfg:
            ent["components"]["body"]["pitch"] = cfg["pitch"]
        if "direction" in cfg:
            ent["components"]["body"]["direction"] = cfg["direction"]
        entities.append(ent)

    return {
        "schema_version": 2,
        "name": "beach-herd",
        "world": sc_solo.world.model_dump(mode="json"),
        "entities": entities,
        "solver": sc_solo.solver.model_dump(mode="json"),
    }


def test_spatiotemporal_wind_field_dynamics():
    """Verify spatial wave propagation and temporal gust modulation of wind field."""
    v0 = 7.0
    amp = 3.0
    omega = 1.2
    kx = 0.4
    field = SpatiotemporalWindField(v0=v0, amplitude=amp, omega=omega, kx=kx)

    # Base at t=0, x=0: v = 7.0 + 3.0 * sin(0) = 7.0
    assert field.velocity(0.0, 0.0) == pytest.approx(7.0, rel=1e-5)

    # At t = pi / (2 * omega), x = 0: sin(pi/2) = 1 -> 10.0
    t_peak = math.pi / (2.0 * omega)
    assert field.velocity(t_peak, 0.0) == pytest.approx(10.0, rel=1e-5)

    # At t = 0, x = pi / (2 * kx): sin(pi/2) = 1 -> 10.0
    x_peak = math.pi / (2.0 * kx)
    assert field.velocity(0.0, x_peak) == pytest.approx(10.0, rel=1e-5)

    # 2D Vector evaluation
    vx, vy = field.vector(0.0, 0.0)
    assert vx == pytest.approx(7.0, rel=1e-5)
    assert vy == pytest.approx(0.0, abs=1e-5)


def test_dynamic_tide_water_level_dynamics():
    """Verify sinusoidal coastal tide elevation model: z_water(t) = z0 + h_tide * sin(omega_tide * t)."""
    z0 = 0.05
    h_tide = 0.20
    omega = 0.8
    tide = DynamicTideField(z0=z0, h_tide=h_tide, omega_tide=omega)

    # At t=0: z = 0.05
    assert tide.water_level(0.0) == pytest.approx(0.05, abs=1e-6)

    # Peak high tide: t = pi / (2 * omega): z = 0.05 + 0.20 = 0.25 m
    t_high = math.pi / (2.0 * omega)
    assert tide.water_level(t_high) == pytest.approx(0.25, abs=1e-5)

    # Low tide: t = 3 * pi / (2 * omega): z = 0.05 - 0.20 = -0.15 m
    t_low = 3.0 * math.pi / (2.0 * omega)
    assert tide.water_level(t_low) == pytest.approx(-0.15, abs=1e-5)

    # Submergence checks
    assert tide.is_submerged(z_tip=0.10, t=t_high)  # 0.10 <= 0.25
    assert not tide.is_submerged(z_tip=0.30, t=t_high)  # 0.30 > 0.25
    assert tide.submergence_depth(z_tip=0.15, t=t_high) == pytest.approx(0.10, abs=1e-5)


def test_herd_beach_multi_walker_bumper_repulsion():
    """Verify mutual bumper repulsion forces push colliding walkers apart without overlap."""
    # Place two walkers along the same track (y = 0.0), close together
    sc_doc = _make_herd_scenario([
        {"name": "walkerA", "x": 0.0, "y": 0.0, "direction": 1},
        {"name": "walkerB", "x": 0.28, "y": 0.0, "direction": -1},  # heading toward walkerA
    ])

    wind = SpatiotemporalWindField(v0=4.0, amplitude=1.0)
    tide = DynamicTideField(z0=-0.5, h_tide=0.05)  # low tide, dry beach

    res = run_herd(
        sc=sc_doc,
        wind_field=wind,
        tide_field=tide,
        duration=1.2,
        bumper_distance=0.35,
        repulsion_k=600.0,
        repulsion_c=30.0,
    )

    assert isinstance(res, HerdResult)
    assert "walkerA" in res.walkers
    assert "walkerB" in res.walkers

    trajA = res.walkers["walkerA"]
    trajB = res.walkers["walkerB"]

    # Verify bumper repulsion forces were triggered during the interaction
    assert len(res.collisions) > 0, "Expected mutual bumper collision events"

    # Repulsive forces exerted on both walkers
    max_fA = np.max(np.abs(trajA.repulsion_force_x))
    max_fB = np.max(np.abs(trajB.repulsion_force_x))
    assert max_fA > 1.0, f"Expected non-zero bumper repulsion on walkerA, got {max_fA}"
    assert max_fB > 1.0, f"Expected non-zero bumper repulsion on walkerB, got {max_fB}"

    # Minimum distance between walkers remains bounded (no interpenetration or collapse)
    min_dist = np.min(trajB.x - trajA.x)
    assert min_dist > 0.05, f"Expected bumper clearance maintained, got min distance {min_dist} m"


def test_herd_beach_tide_water_feeler_reverse_reflex():
    """Verify that a rising coastal tide triggers the water feeler vacuum reflex, reversing direction."""
    # Place a walker on the beach slope near the water line
    sc_doc = _make_herd_scenario([
        {"name": "tideWalker", "x": 0.0, "y": 0.0, "direction": -1},
    ])

    # Tide starts below feeler, then rapidly rises above feeler tip
    # Jansen walker hip_height is ~0.16 m; feeler tip hangs near ground ~0.05 m
    tide = DynamicTideField(z0=0.08, h_tide=0.06, omega_tide=2.0)

    res = run_herd(
        sc=sc_doc,
        wind_field=SpatiotemporalWindField(v0=2.0),
        tide_field=tide,
        duration=1.5,
    )

    traj = res.walkers["tideWalker"]

    # Feeler should sense immersion as water level rises
    assert np.any(traj.feeler_immersed), "Expected feeler tip to become immersed in rising tide"

    # Vacuum pressure builds up rapidly in the submerged sensing tube
    assert np.max(traj.feeler_vacuum) > 10000.0, "Expected vacuum suction > 10 kPa during immersion"

    # Direction reflex triggered: walker reverses direction from -1 to +1
    assert np.any(traj.feeler_tripped), "Expected water feeler trip to fire"
    assert traj.direction[-1] == 1, "Expected walker direction to reverse to flee rising water"


def test_herd_beach_storm_anchor_deployment_on_tilt():
    """Verify that when a walker is tilted beyond critical threshold, storm anchor deploys into sand."""
    # Place walker with free pitch joint so tilting is physically dynamic
    sc_doc = _make_herd_scenario([
        {"name": "anchorWalker", "x": 0.0, "y": 0.0, "pitch": "free"},
        {"name": "pusherWalker", "x": -0.22, "y": 0.0, "direction": 1},  # bumps from behind
    ])

    wind = SpatiotemporalWindField(v0=12.0, amplitude=4.0)  # Strong gale wind
    tide = DynamicTideField(z0=-0.5, h_tide=0.05)

    res = run_herd(
        sc=sc_doc,
        wind_field=wind,
        tide_field=tide,
        duration=1.8,
        repulsion_k=800.0,
    )

    traj_anchor = res.walkers["anchorWalker"]

    # When tilted / pushed, anchor is deployed
    assert np.any(traj_anchor.anchor_deployed), "Expected storm anchor to deploy on high tilt/push"

    # Anchor generates significant geotechnical holding force (> 500 N) pinning the walker
    max_holding_force = np.max(traj_anchor.anchor_holding_force)
    assert max_holding_force > 500.0, f"Expected soil holding force > 500 N, got {max_holding_force}"


def test_herd_beach_zero_wind_no_self_driving():
    """Verify that in zero wind with sail drive, walkers do not self-drive (conservation of energy)."""
    sc_doc = _make_herd_scenario([
        {"name": "sailWalker", "x": 0.0, "y": 0.0, "direction": 1},
    ])
    # Set drive to sail
    sc_doc["entities"][0]["components"]["drive"] = {
        "kind": "sail",
        "sail_area": 0.04,
        "sail_radius": 0.04,
        "sail_drag_coeff": 1.2,
        "sail_gear": 1.0,
    }

    # Zero wind, zero waves
    wind = SpatiotemporalWindField(v0=0.0, amplitude=0.0)
    tide = DynamicTideField(z0=-1.0, h_tide=0.0)

    res = run_herd(
        sc=sc_doc,
        wind_field=wind,
        tide_field=tide,
        duration=1.0,
    )

    traj = res.walkers["sailWalker"]
    # Total horizontal displacement must be essentially zero (strictly resting/settling under gravity, < 1 mm)
    dx = float(np.max(np.abs(traj.x - traj.x[0])))
    assert dx < 1e-3, f"Expected zero forward walk in zero wind, got settlement {dx} m"
    # Crank must not rotate (no self-driving power)
    dpsi = float(np.max(np.abs(traj.psi - traj.psi[0])))
    assert dpsi < 0.01, f"Expected crank to stay stationary in zero wind, got rotation {dpsi} rad"
    assert res.energy_account["work_in"] == pytest.approx(0.0, abs=1e-6)


def test_herd_beach_recorded_wind_field_reproducibility():
    """Verify loading coastal recorded wind dataset and deterministic replay."""
    from strandbeest_sim import RecordedWindField
    from pathlib import Path

    dataset_path = Path(__file__).resolve().parents[3] / "data" / "winds" / "scheveningen_beach_gusts.json"
    wind = RecordedWindField.load(dataset_path)

    assert wind.provenance.get("synthetic") is True
    assert "Scheveningen" in wind.provenance["source"]
    assert wind.provenance["units"]["speed"] == "m/s"

    # Evaluate at known timestamps
    v0 = wind.velocity(0.0)
    v3 = wind.velocity(3.0)
    assert v0 > 4.0
    assert v3 > 6.0

    sc_doc = _make_herd_scenario([
        {"name": "w1", "x": 0.0, "y": 0.0},
    ])

    res1 = run_herd(sc=sc_doc, wind_field=wind, duration=1.0)
    res2 = run_herd(sc=sc_doc, wind_field=wind, duration=1.0)

    # Identical replay
    np.testing.assert_allclose(res1.walkers["w1"].x, res2.walkers["w1"].x, atol=1e-10)


def test_herd_beach_event_stream_and_energy_account():
    """Verify that collisions, reflexes, and energy accounting are properly recorded in HerdResult."""
    sc_doc = _make_herd_scenario([
        {"name": "wA", "x": 0.0, "y": 0.0, "direction": 1},
        {"name": "wB", "x": 0.28, "y": 0.0, "direction": -1},
    ])

    wind = SpatiotemporalWindField(v0=5.0, amplitude=1.0)
    tide = DynamicTideField(z0=0.08, h_tide=0.08, omega_tide=2.0)

    res = run_herd(
        sc=sc_doc,
        wind_field=wind,
        tide_field=tide,
        duration=1.5,
        bumper_distance=0.35,
    )

    # Check events list exists and contains expected event categories
    assert hasattr(res, "events")
    event_types = {e["type"] for e in res.events}
    assert "collision" in event_types or len(res.collisions) > 0

    # Check energy account ledger
    assert hasattr(res, "energy_account")
    ea = res.energy_account
    assert "work_in" in ea
    assert "bumper_dissipation" in ea
    assert ea["work_in"] >= 0.0

