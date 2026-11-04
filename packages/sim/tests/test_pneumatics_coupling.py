"""System-level tests for closed-loop pneumatic-mechanical coupling (H3-02)."""

from __future__ import annotations

import math

import pytest

from strandbeest_common.scenario import flatten, to_v2
from strandbeest_sim.config import Scenario, sim_config
from strandbeest_sim.fluids.constants import P_ATM
from strandbeest_sim.fluids.coupling import PneumaticCoupler
from strandbeest_sim.runner import make_sim, run
from strandbeest_sim.skeptic import audit_legacy


def test_scenario_v1_v2_pneumatics_roundtrip() -> None:
    """Scenario v2 and flat ScenarioV1 round-trip with and without pneumatics."""
    v2_with_pneu = {
        "schema_version": 2,
        "name": "pneu_walker",
        "world": {},
        "entities": [
            {
                "name": "walker",
                "kind": "walker",
                "components": {
                    "linkage": {},
                    "body": {"legs": 6},
                    "drive": {"kind": "motor"},
                    "pneumatics": {
                        "bottle_count": 2,
                        "bottle_volume_l": 1.5,
                        "precharge_pa": 101325.0,
                        "pump_bore_m": 0.03,
                        "pump_stroke_m": 0.05,
                        "feeler_enabled": True,
                        "anchor_enabled": True,
                    },
                },
            }
        ],
    }
    sc = Scenario.model_validate(v2_with_pneu)
    cfg = sim_config(sc)
    assert cfg.pneumatics is not None
    assert cfg.pneumatics.bottle_count == 2
    assert cfg.pneumatics.bottle_volume_l == pytest.approx(1.5)

    flat = flatten(sc.model_dump(mode="json"))
    assert "pneumatics" in flat
    back_v2 = to_v2(flat)
    assert back_v2["entities"][0]["components"]["pneumatics"]["bottle_count"] == 2

    # Without pneumatics, flat ScenarioV1 omits the optional key
    cfg_default = sim_config({})
    assert cfg_default.pneumatics is None
    assert "pneumatics" not in cfg_default.model_dump(mode="json")


@pytest.mark.parametrize("backend", ["mujoco", "k2"])
def test_closed_loop_pneumatic_charging_and_unified_energy_ledger(backend: str) -> None:
    """Motor-driven walker charges PET bottles; crank reaction torque and unified energy ledger hold."""
    base_doc = {
        "schema_version": 1,
        "walker": {"legs": 6},
        "drive": {"kind": "motor", "omega": 2.0, "ramp": 0.1},
        "run": {"settle": 0.05, "revolutions": 0.6, "record_every": 10, "frame_rate": 0.0},
    }
    res_no_pneu = run(base_doc, backend=backend)
    assert "pneumatics" not in res_no_pneu.metrics

    pneu_doc = {
        **base_doc,
        "pneumatics": {
            "bottle_count": 1,
            "bottle_volume_l": 0.5,
            "precharge_pa": P_ATM,
            "pump_bore_m": 0.03,
            "pump_stroke_m": 0.05,
            "feeler_enabled": False,
            "anchor_enabled": False,
        },
    }
    res_pneu = run(pneu_doc, backend=backend)
    pm = res_pneu.metrics["pneumatics"]

    assert pm["mode"] == "charge"
    assert pm["bottle_pressure_rise_pa"] > 400.0
    assert pm["final_bottle_pressure_pa"] > pm["initial_bottle_pressure_pa"]
    assert pm["pump_work_j"] > 0.15
    assert pm["gas_compression_work_j"] > 0.15
    assert pm["mass_conservation_relative_error"] < 1e-10
    assert abs(pm["energy_residual_j"]) < 1e-6

    # Time series recorded
    assert "p_cyl" in res_pneu.series
    assert "p_bottle" in res_pneu.series
    assert "tau_pump" in res_pneu.series
    assert "e_pneumatics" in res_pneu.series
    assert res_pneu.series["p_bottle"][-1] > res_pneu.series["p_bottle"][0]

    # Multibody energy audit passes with coupled pump reaction torque
    legacy_issues = [i.check for i in audit_legacy(res_pneu.scenario, res_pneu.metrics, res_pneu.series)]
    assert "energy" not in legacy_issues


def test_stored_air_windless_walking_and_zero_energy_control() -> None:
    """Pre-charged PET bottles propel a sail walker in zero wind; uncharged bottles do not self-propel."""
    uncharged_doc = {
        "schema_version": 1,
        "walker": {"legs": 6, "unit": 0.002, "mass": 1.0, "foot_radius": 0.003},
        "wind": {"kind": "constant", "speed": 0.0},
        "drive": {"kind": "sail", "crank_friction": 0.002, "crank_damping": 0.001},
        "pneumatics": {
            "bottle_count": 2,
            "bottle_volume_l": 1.0,
            "precharge_pa": P_ATM,
            "pump_bore_m": 0.03,
            "pump_stroke_m": 0.05,
            "feeler_enabled": False,
            "anchor_enabled": False,
        },
        "run": {
            "settle": 0.1,
            "revolutions": 0.5,
            "max_time": 1.0,
            "give_up_after": 0.4,
            "record_every": 10,
            "frame_rate": 0.0,
        },
    }
    res_uncharged = run(uncharged_doc, backend="mujoco")
    assert res_uncharged.stalled is True
    assert float(res_uncharged.psi[-1]) < 0.2
    assert res_uncharged.metrics["pneumatics"]["pump_work_j"] >= 0.0

    charged_doc = {
        **uncharged_doc,
        "pneumatics": {
            **uncharged_doc["pneumatics"],
            "precharge_pa": 350_000.0,
        },
    }
    res_charged = run(charged_doc, backend="mujoco")
    pm = res_charged.metrics["pneumatics"]
    assert res_charged.stalled is False
    assert float(res_charged.psi[-1]) > 2.9
    assert abs(float(res_charged.x[-1] - res_charged.x[0])) > 0.005
    assert pm["mode"] == "discharge"
    assert pm["final_bottle_pressure_pa"] < pm["initial_bottle_pressure_pa"]
    assert pm["pump_work_j"] < -0.05  # net mechanical work delivered BY gas TO crank
    assert pm["mass_conservation_relative_error"] < 1e-10
    assert pm["energy_conservation_relative_error"] < 1e-5
    assert abs(pm["energy_residual_j"]) < 1e-3


def test_closed_loop_water_feeler_and_storm_anchor_reflexes() -> None:
    """Water feeler immersion trips directional valve; steep slope triggers storm anchor deployment."""
    doc = {
        "schema_version": 1,
        "walker": {"legs": 6},
        "terrain": {"kind": "flat", "slope_deg": 20.0, "water_level_m": 0.08},
        "drive": {"kind": "motor", "omega": 2.0, "ramp": 0.05},
        "pneumatics": {
            "bottle_count": 2,
            "bottle_volume_l": 2.0,
            "precharge_pa": 500_000.0,
            "pump_bore_m": 0.03,
            "pump_stroke_m": 0.05,
            "feeler_enabled": True,
            "anchor_enabled": True,
        },
        "run": {"settle": 0.05, "revolutions": 0.5, "record_every": 5, "frame_rate": 0.0},
    }
    res = run(doc, backend="mujoco")
    pm = res.metrics["pneumatics"]
    assert pm["feeler_tripped"] is True
    assert pm["valve_state"] == -1
    assert pm["anchor_deployed"] is True
    assert pm["anchor_holding_force_n"] > 1500.0


def test_pneumatic_coupler_snapshot_and_restore_determinism() -> None:
    """Checkpointing both PhysicsBackend and PneumaticCoupler reproduces identical continuation trajectories."""
    cfg = sim_config(
        {
            "schema_version": 1,
            "walker": {"legs": 6},
            "drive": {"kind": "motor", "omega": 2.0, "ramp": 0.05},
            "pneumatics": {
                "bottle_count": 1,
                "bottle_volume_l": 0.5,
                "precharge_pa": P_ATM,
                "pump_bore_m": 0.03,
                "pump_stroke_m": 0.05,
                "feeler_enabled": True,
                "anchor_enabled": True,
            },
        }
    )
    sim = make_sim(cfg, "mujoco")
    be = sim.backend
    dt = be.timestep
    from strandbeest_sim.registry import drives

    drive = drives.get(cfg.drive.kind)(sim)
    pneu = PneumaticCoupler(cfg, psi_start=sim.psi())

    t = 0.0
    for _ in range(200):
        drive.control(sim, t, driving=True)
        pneu.pre_step(sim, drive, t)
        be.step()
        pneu.post_step(sim, be.step_observation(), drive, dt, t)
        t += dt

    be_snap = be.snapshot()
    pneu_snap = pneu.snapshot()
    target_saved = drive.target
    t_saved = t

    # Branch A: step 200 more steps
    for _ in range(200):
        drive.control(sim, t, driving=True)
        pneu.pre_step(sim, drive, t)
        be.step()
        pneu.post_step(sim, be.step_observation(), drive, dt, t)
        t += dt
    sample_a = pneu.sample()
    x_a = be.body_position("torso")[0]

    # Restore and re-run Branch B
    be.restore(be_snap)
    pneu.restore(pneu_snap)
    drive.target = target_saved
    t = t_saved
    for _ in range(200):
        drive.control(sim, t, driving=True)
        pneu.pre_step(sim, drive, t)
        be.step()
        pneu.post_step(sim, be.step_observation(), drive, dt, t)
        t += dt
    sample_b = pneu.sample()
    x_b = be.body_position("torso")[0]

    assert x_a == pytest.approx(x_b, abs=1e-12)
    assert sample_a.p_bottle == pytest.approx(sample_b.p_bottle, abs=1e-12)
    assert sample_a.p_cyl == pytest.approx(sample_b.p_cyl, abs=1e-12)
    assert sample_a.e_pneumatics == pytest.approx(sample_b.e_pneumatics, abs=1e-12)
