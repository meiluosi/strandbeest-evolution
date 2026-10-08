"""G-01 / G-04: the energy account closes, loads are recorded, events and the diagnosis find the cause."""

import math

import numpy as np
import pytest
from strandbeest_common import Design, gait_metrics
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.events import detect_events, diagnose

DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")


def go(**ov):
    run_ov = {"frame_rate": 30, "settle": 0.5, "revolutions": 2.1, **ov.pop("run", {})}
    return run(scenario_from_design(DESIGN, {"run": run_ov, **ov}))


@pytest.fixture(scope="module")
def flat():
    return go(run={"revolutions": 3.0})


def test_flat_ground_energy_account_closes_and_is_mostly_contact_dissipation(flat):
    m = flat.metrics
    assert abs(m["energy_residual_share"]) < 0.02  # input = dissipation + change of mechanical energy, within 2 %
    assert 0.93 < m["energy_contact_share"] < 0.99  # about 97 %: the torque on flat ground is mostly slip dissipation (EXPERIMENTS 8)
    assert m["energy_loops_share"] < 0.06 and m["energy_friction_share"] == pytest.approx(0.0, abs=1e-6)
    assert m["energy_window_revs"] == pytest.approx(2.0, abs=0.01) and m["steady_window"] == 1.0
    # the input work per revolution is the mean crank torque times 2 pi
    assert m["energy_in_per_rev"] == pytest.approx(m["mean_torque"] * 2 * math.pi, rel=0.1)


@pytest.mark.slow
@pytest.mark.parametrize("name,ov", [
    ("slope", {"terrain": {"kind": "slope", "slope_deg": 5}}),
    ("sail", {"drive": {"kind": "sail"}, "wind": {"speed": 4.0}, "run": {"give_up_after": 8, "max_time": 60, "frame_rate": 0}}),
])
def test_energy_account_closes_for_other_drives_and_terrains(name, ov):
    r = go(**ov)
    assert abs(r.metrics["energy_residual_share"]) < 0.02, name
    shares = r.metrics["energy_contact_share"] + r.metrics["energy_loops_share"] + r.metrics["energy_friction_share"]
    assert shares < 1.02  # nothing is dissipated twice; the rest went into potential energy (slope) or is the residual


def test_the_foot_loads_carry_the_weight_and_the_series_have_the_right_shapes(flat):
    s = flat.series
    n = len(flat.t)
    legs = DESIGN.walker["legs"]
    assert s["foot_normal"].shape == (n, legs) and s["foot_slip"].shape == (n, legs) and s["foot_tangent"].shape == (n, legs)
    for k in ("loop_residual", "penetration", "kinetic", "potential", "e_in", "e_contact", "e_loops", "e_friction", "crank_reaction"):
        assert s[k].shape == (n,)
    # over whole revolutions the mean ground reaction equals the weight
    psi = flat.psi
    i0, i1 = int(np.searchsorted(psi, 2 * math.pi)), int(np.searchsorted(psi, 3 * 2 * math.pi))
    mass = DESIGN.walker["body_mass_kg"] + flat.scenario.walker.legs * 0  # legs are added below from the bar masses
    from strandbeest_sim.runner import make_sim

    sim = make_sim(flat.scenario)
    mass += sim.info.bar_mass_total
    assert s["foot_normal"][i0:i1].sum(axis=1).mean() == pytest.approx(mass * flat.scenario.environment.gravity, rel=0.05)
    f = flat.frames
    assert f["foot_pos"].shape == (len(f["t"]), legs, 3) and f["foot_force"].shape == f["foot_pos"].shape
    assert f["foot_slip"].shape == (len(f["t"]), legs) and f["com"].shape == (len(f["t"]), 3)


def test_footfall_stance_fraction_is_recorded_and_differs_from_the_kinematic_duty_factor(flat):
    """Honest comparison: the leg's path is flat (kinematic duty 0.43) for 43 % of the revolution, but the foot is in contact
    with the ground for about 35 % of the time in the simulation. Both numbers are shown to the user (G-02)."""
    n = flat.series["foot_normal"]
    i0 = int(np.searchsorted(flat.psi, 2 * math.pi))
    stance = float((n[i0:] > 1e-6).mean())
    kinematic = gait_metrics(DESIGN.spec).duty
    assert kinematic == pytest.approx(0.433, abs=0.01)
    assert 0.30 < stance < 0.40 and stance < kinematic


def test_events_on_flat_ground_are_a_regular_gait(flat):
    ev = detect_events(flat)
    kinds = {e["kind"] for e in ev}
    assert {"start", "touchdown", "liftoff"} <= kinds
    legs = DESIGN.walker["legs"]
    for leg in range(legs):
        td = [e["t"] for e in ev if e["kind"] == "touchdown" and e["leg"] == leg]
        assert len(td) >= 2
        period = np.diff(td)
        assert float(period.std()) < 0.1 * float(period.mean())  # one touchdown per revolution, evenly spaced
    assert [e["t"] for e in ev] == sorted(e["t"] for e in ev)


def test_diagnosis_flat_ground_finds_nothing_wrong(flat):
    d = diagnose(flat)
    assert d[0]["code"] == "ok" and d[0]["severity"] == "info"


@pytest.mark.slow
def test_diagnosis_step_scene_is_blocked_by_terrain_and_the_torque_limit():
    r = go(terrain={"kind": "step", "params": {"distance": 0.15, "height": 0.012}}, run={"revolutions": 2.5, "frame_rate": 0})
    d = diagnose(r)
    top = d[0]
    assert top["code"] == "blocked_by_terrain_torque_limit" and top["severity"] == "error"
    ev = top["evidence"]
    assert ev["terrain"] == "step" and ev["torque_limit_nm"] == 0.3 and ev["times_at_limit"] >= 2 and ev["advance_efficiency"] < 0.3


@pytest.mark.slow
def test_diagnosis_sail_on_mars_is_too_weak_to_start_or_to_run():
    mars = {"environment": {"gravity": 3.73, "air_density": 0.02}, "drive": {"kind": "sail"}}
    stalled = go(**mars, wind={"speed": 2.0}, run={"revolutions": 1.0, "give_up_after": 8, "max_time": 40, "frame_rate": 0})
    d = diagnose(stalled)
    assert stalled.stalled and d[0]["code"] == "sail_torque_insufficient"
    assert d[0]["evidence"]["sail_standstill_torque_nm"] == pytest.approx(0.00115, rel=0.02)
    slow = go(**mars, wind={"speed": 3.0}, run={"revolutions": 1.0, "give_up_after": 8, "max_time": 40, "frame_rate": 0})
    d2 = diagnose(slow)
    assert not slow.stalled and d2[0]["code"] == "sail_weak" and d2[0]["evidence"]["ratio"] < 0.15


@pytest.mark.slow
def test_soft_contact_lights_up_the_invariants_and_the_diagnosis():
    r = go(terrain={"kind": "soft", "params": {"stiffness": 4000.0, "damping": 120.0}}, run={"revolutions": 2.1, "frame_rate": 0})
    codes = [x["code"] for x in diagnose(r)]
    assert "deep_sinkage" in codes
    assert r.metrics["max_penetration"] > 0.005
