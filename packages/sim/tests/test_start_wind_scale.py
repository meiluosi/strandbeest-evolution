"""W-05: the scaling helpers and the pre-registered prediction of the start-wind-vs-scale experiment.

The helpers are pure functions (no simulation), so they are tested here; the end-to-end sweep is marked slow.
"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# the script is imported by name (not by path) so that the worker processes can import it too
sys.path.insert(0, str(ROOT / "scripts"))

import start_wind_scale as sws  # noqa: E402


@pytest.fixture(scope="module")
def base():
    return sws.base_config()


# ---------------------------------------------------------------- the scaling rules


def test_every_length_scales_with_L(base):
    ov = sws.scale_overrides(base, 2.0, 1.0)
    assert ov["walker"]["unit"] == pytest.approx(base.walker.unit * 2)
    assert ov["walker"]["body_length"] == pytest.approx(base.walker.body_length * 2)
    assert ov["walker"]["lateral_spacing"] == pytest.approx(base.walker.lateral_spacing * 2)
    assert ov["walker"]["foot_radius"] == pytest.approx(base.walker.foot_radius * 2)
    assert ov["drive"]["sail_radius"] == pytest.approx(base.drive.sail_radius * 2)


def test_the_body_mass_scales_as_L_to_the_p(base):
    for p in (1.0, 2.0, 3.0):
        ov = sws.scale_overrides(base, 2.0, p)
        assert ov["walker"]["body_mass"] == pytest.approx(base.walker.body_mass * 2**p)


def test_the_leg_mass_scales_as_L_to_the_p(base):
    """tube_mass_per_m x L**(p-1) times a bar length x L gives a bar mass x L**p."""
    for p in (1.0, 2.0, 3.0):
        ov = sws.scale_overrides(base, 2.0, p)
        assert ov["walker"]["tube_mass_per_m"] == pytest.approx(base.walker.tube_mass_per_m * 2 ** (p - 1))
        bar_length_m = 50.0 * base.walker.unit  # a bar of 50 length units, in metres
        scaled_bar_length = bar_length_m * 2
        assert ov["walker"]["tube_mass_per_m"] * scaled_bar_length == pytest.approx(
            base.walker.tube_mass_per_m * bar_length_m * 2**p
        )


def test_the_sail_area_scales_as_L_squared_and_the_gear_does_not(base):
    ov = sws.scale_overrides(base, 3.0, 1.0)
    assert ov["drive"]["sail_area"] == pytest.approx(base.drive.sail_area * 9)
    assert ov["drive"]["sail_gear"] == base.drive.sail_gear  # dimensionless: it multiplies the crank torque only


def test_the_servo_that_holds_the_weight_scales_with_the_load_torque(base):
    for p in (1.0, 2.0, 3.0):
        ov = sws.scale_overrides(base, 2.0, p)
        assert ov["drive"]["kp"] == pytest.approx(base.drive.kp * 2 ** (p + 1))
        assert ov["drive"]["max_torque"] == pytest.approx(base.drive.max_torque * 2 ** (p + 1))


def test_L_one_changes_nothing(base):
    """The self-check: at L = 1 the scaled design is the base design, whatever p is."""
    for p in (1.0, 2.0, 3.0):
        ov = sws.scale_overrides(base, 1.0, p)
        assert ov["walker"]["unit"] == pytest.approx(base.walker.unit)
        assert ov["walker"]["body_mass"] == pytest.approx(base.walker.body_mass)
        assert ov["walker"]["tube_mass_per_m"] == pytest.approx(base.walker.tube_mass_per_m)
        assert ov["drive"]["sail_area"] == pytest.approx(base.drive.sail_area)
        assert ov["drive"]["sail_radius"] == pytest.approx(base.drive.sail_radius)
        assert ov["drive"]["sail_gear"] == base.drive.sail_gear


def test_the_joint_friction_is_an_absolute_value(base):
    """The pin friction is an absolute Coulomb torque per pin, not a coefficient: it does not scale with L."""
    for friction in (0.0, 0.0005, 0.002):
        ov = sws.scale_overrides(base, 4.0, 3.0, joint_friction=friction)
        assert ov["walker"]["joint_friction"] == friction


def test_the_overrides_are_a_valid_scenario(base):
    """The overrides must survive the scenario schema (they are merged into the scenario by from_design)."""
    from strandbeest_sim import scenario_from_design, sim_config

    for L, p in ((0.25, 1.0), (1.0, 2.0), (4.0, 3.0)):
        ov = sws.scale_overrides(base, L, p, joint_friction=0.002)
        sc = sim_config(scenario_from_design(sws.design(), ov))
        assert sc.walker.unit == pytest.approx(base.walker.unit * L)
        assert sc.walker.body_mass == pytest.approx(base.walker.body_mass * L**p)


# ---------------------------------------------------------------- the pre-registered prediction


def test_the_predicted_slopes_of_the_two_load_models():
    """Lift dominated: the load torque is L**(p+1) and the sail torque L**3 v**2, so v ~ L**((p-2)/2)."""
    assert sws.predicted_slope(1.0, "lift") == pytest.approx(-0.5)
    assert sws.predicted_slope(2.0, "lift") == pytest.approx(0.0)
    assert sws.predicted_slope(3.0, "lift") == pytest.approx(0.5)
    # WIND.md section 4 premise (friction ~ normal force ~ weight) gives the same exponent
    for p in (1.0, 2.0, 3.0):
        assert sws.predicted_slope(p, "pin_friction_weight") == pytest.approx(sws.predicted_slope(p, "lift"))
    # as coded, the pin friction is an absolute torque: the friction dominated threshold is v ~ L**(-1.5)
    # (the pre-registration wrote +1.5; the balance L**3 * v**2 = const gives v = sqrt(const) * L**(-3/2))
    for p in (1.0, 2.0, 3.0):
        assert sws.predicted_slope(p, "pin_friction_absolute") == pytest.approx(-1.5)
    assert sws.predicted_slope(1.0, "time_criterion") == pytest.approx(1.0)
    with pytest.raises(ValueError):
        sws.predicted_slope(1.0, "nonsense")


def test_the_absolute_pin_friction_exponent_is_negative():
    """The balance of the absolute pin friction is L**3 * v**2 = const, so v = sqrt(const) * L**(-3/2).

    A smaller machine therefore needs MORE wind, not less. The pre-registration wrote +1.5 (a sign slip, corrected on
    2026-10-21); this test pins the sign so it cannot be flipped again silently.
    """
    for p in (1.0, 2.0, 3.0):
        assert sws.predicted_slope(p, "pin_friction_absolute") < 0.0
    # the friction dominated threshold falls with the scale: a factor 2 smaller machine needs 2**1.5 more wind
    assert sws.predicted_slope(1.0, "pin_friction_absolute") == pytest.approx(-math.log(2.0**1.5) / math.log(2.0))


def test_the_predicted_start_wind_is_normalised_at_L_one():
    v1 = sws.predicted_start_wind(1.0, 1.0)
    assert v1 == pytest.approx(sws.V_REF_M_S)
    assert sws.predicted_start_wind(1.0, 3.0) == pytest.approx(sws.V_REF_M_S)


def test_the_predicted_start_wind_has_the_predicted_slope_without_the_time_term():
    """With a very long horizon the time term vanishes and the curve is a pure power law of exponent (p-2)/2."""
    for p in (1.0, 2.0, 3.0):
        xs = [0.5, 1.0, 2.0, 4.0]
        ys = [sws.predicted_start_wind(x, p, max_time_s=1e6) for x in xs]
        assert sws.log_log_slope(xs, ys) == pytest.approx((p - 2) / 2, abs=1e-3)


def test_the_predicted_start_wind_grows_with_the_scale_for_a_solid_body():
    """p = 3: the load grows like L**4 and the sail torque like L**3, so the bigger machine needs more wind."""
    assert sws.predicted_start_wind(4.0, 3.0) > sws.predicted_start_wind(1.0, 3.0)
    # p = 1: a thin wall machine gets cheaper with scale (without the time term of the 40 s criterion)
    assert sws.predicted_start_wind(4.0, 1.0, max_time_s=1e6) < sws.predicted_start_wind(1.0, 1.0, max_time_s=1e6)
    # with the 40 s criterion the extra term omega_req * gear * r grows like L and dominates at L = 4
    assert sws.predicted_start_wind(4.0, 1.0) > sws.predicted_start_wind(1.0, 1.0)


def test_the_log_log_slope_of_a_power_law():
    xs = [1.0, 2.0, 4.0, 8.0]
    assert sws.log_log_slope(xs, [3.0 * x**0.5 for x in xs]) == pytest.approx(0.5)
    assert sws.log_log_slope(xs, [3.0 * x ** (-0.5) for x in xs]) == pytest.approx(-0.5)
    assert math.isnan(sws.log_log_slope([1.0], [1.0]))


# ---------------------------------------------------------------- the sweep bookkeeping


def test_the_cell_keys_are_unique_and_resumable():
    jobs = sws.build_jobs((0.25, 1.0, 4.0), (1.0, 3.0), (0.5, 1.0), (0.0, 0.002), "mujoco", (1.0,), 40.0)
    keys = [j["key"] for j in jobs]
    assert len(keys) == len(set(keys))
    # the friction band at friction 0 is the cell of the main sweep: it is not simulated twice
    assert sum(1 for j in jobs if j["scale"] == 1.0 and j["mass_exponent"] == 1.0
               and j["backend"] == "mujoco" and j["joint_friction"] == 0.0) == 1


def test_the_merged_cells_keep_the_first_result():
    a = {"key": "k", "scale": 1.0, "estimate_m_s": 1.0}
    b = {"key": "k", "scale": 1.0, "estimate_m_s": 2.0}
    assert sws.merge_cells([a], [b])[0]["estimate_m_s"] == 1.0


# ---------------------------------------------------------------- the L = 1 alias


def test_the_L_one_cells_of_the_other_mass_exponents_are_aliases():
    """At L = 1 the scaled design does not depend on p, so only the first exponent is simulated."""
    jobs = sws.build_jobs((0.5, 1.0), (1.0, 3.0), (0.5,), (0.0,), "mujoco", (), 40.0, ())
    by_key = {j["key"]: j for j in jobs}
    assert "alias_of" not in by_key["mujoco|L=1|p=1|jf=0"]
    alias = by_key["mujoco|L=1|p=3|jf=0"]
    assert alias["alias_of"] == "mujoco|L=1|p=1|jf=0"
    # the alias is not simulated: only the cells without an alias are jobs to run
    assert sum(1 for j in jobs if j.get("alias_of")) == 1


def test_an_alias_carries_the_numbers_of_the_cell_it_points_at():
    source = {"key": "mujoco|L=1|p=1|jf=0", "scale": 1.0, "mass_exponent": 1.0, "estimate_m_s": 0.5,
              "lo_m_s": 0.489, "hi_m_s": 0.5106, "found": True, "simulations": 6}
    alias = {"key": "mujoco|L=1|p=3|jf=0", "scale": 1.0, "mass_exponent": 3.0, "alias_of": source["key"]}
    out = sws.resolve_aliases([source, alias])
    assert len(out) == 2
    a = next(c for c in out if c["key"] == alias["key"])
    assert a["estimate_m_s"] == 0.5
    assert a["mass_exponent"] == 3.0
    assert a["alias_of"] == source["key"]
    # an alias whose source is missing is dropped (the next run re-creates it)
    assert sws.resolve_aliases([alias]) == []


def test_an_alias_is_built_from_the_job_list_when_it_was_not_simulated():
    """The alias cells are not simulated, so they have to be created from the job list of the sweep."""
    source = {"key": "mujoco|L=1|p=1|jf=0", "scale": 1.0, "mass_exponent": 1.0, "estimate_m_s": 0.5,
              "lo_m_s": 0.489, "hi_m_s": 0.5106, "found": True, "simulations": 6}
    jobs = sws.build_jobs((1.0,), (1.0, 3.0), (1.0,), (0.0,), "mujoco", (), 40.0, ())
    out = sws.resolve_aliases([source], jobs)
    alias = next(c for c in out if c["key"] == "mujoco|L=1|p=3|jf=0")
    assert alias["estimate_m_s"] == 0.5
    assert alias["mass_exponent"] == 3.0
    assert alias["alias_of"] == "mujoco|L=1|p=1|jf=0"
    # the source cell is still there
    assert sum(1 for c in out if c["key"] == "mujoco|L=1|p=1|jf=0") == 1


def test_the_summary_reports_the_slopes_and_the_non_starting_cells():
    cells = [
        {"key": "a", "scale": 1.0, "mass_exponent": 1.0, "joint_friction_nm": 0.0, "backend": "mujoco",
         "lo_m_s": 0.4, "hi_m_s": 0.5, "estimate_m_s": 0.45, "found": True, "simulations": 6, "predicted_m_s": 0.45},
        {"key": "b", "scale": 2.0, "mass_exponent": 1.0, "joint_friction_nm": 0.0, "backend": "mujoco",
         "lo_m_s": 0.3, "hi_m_s": 0.4, "estimate_m_s": 0.35, "found": True, "simulations": 6, "predicted_m_s": 0.35},
        {"key": "c", "scale": 0.25, "mass_exponent": 1.0, "joint_friction_nm": 0.002, "backend": "mujoco",
         "lo_m_s": 20.0, "hi_m_s": float("inf"), "estimate_m_s": float("nan"), "found": False, "simulations": 8,
         "predicted_m_s": 9.0, "does_not_start": True, "max_wind_tried_m_s": 20.0, "note": "does not start"},
    ]
    summ = sws.summarise(cells)
    assert summ["slopes"]["p=1"]["measured"] == pytest.approx(math.log(0.35 / 0.45) / math.log(2.0))
    assert summ["slopes"]["p=1"]["predicted_lift"] == pytest.approx(-0.5)
    assert len(summ["does_not_start"]) == 1
    assert summ["does_not_start"][0]["max_wind_tried_m_s"] == 20.0


@pytest.mark.slow
def test_the_end_to_end_sweep_runs_a_small_cell():
    """One real cell of the sweep: the unscaled walker must need the W-03 baseline wind (EXPERIMENTS.md section 28)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = f"{tmp}/w05.json"
        # the probe cells are switched off: this test asserts on the L = 1 baseline cell only, and the cells of the
        # output file are sorted by key (so "L=0.1" would come before "L=1" and be picked up by index).
        sws.main([out, "1", "--scales", "1.0", "--mass-exponents", "1", "--friction-scales", "1.0",
                  "--frictions", "0", "--no-k2", "--probe-cells", ""])
        import json

        doc = json.load(open(out))
        cell = next(c for c in doc["cells"] if c["key"] == "mujoco|L=1|p=1|jf=0")
        assert cell["found"]
        assert 0.4 < cell["estimate_m_s"] < 0.6  # the baseline of section 28 is (0.479, 0.500] m/s
        # the bracket of section 28 is (0.479, 0.500]; the search here starts from a different guess (the predicted
        # 0.489), so the bisection path differs and the interval is not bit-identical: it must still overlap it.
        assert cell["hi_m_s"] >= 0.479
        assert cell["lo_m_s"] <= 0.500
