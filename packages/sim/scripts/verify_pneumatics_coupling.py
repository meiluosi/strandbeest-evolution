"""Generate reproducible experiment record for H3-02 closed-loop pneumatic-mechanical coupling."""

from __future__ import annotations

import json
from pathlib import Path

from strandbeest_sim.audit import audit_legacy
from strandbeest_sim.fluids.constants import P_ATM
from strandbeest_sim.runner import run

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    # 1. Closed-loop charging (MuJoCo & K2)
    base_doc = {
        "schema_version": 1,
        "walker": {"legs": 6},
        "drive": {"kind": "motor", "omega": 2.0, "ramp": 0.1},
        "run": {"settle": 0.05, "revolutions": 1.0, "record_every": 10, "frame_rate": 0.0},
    }
    pneu_charge_doc = {
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
    res_mj = run(pneu_charge_doc, backend="mujoco")
    res_k2 = run(pneu_charge_doc, backend="k2")
    mj_issues = [i.check for i in audit_legacy(res_mj.scenario, res_mj.metrics, res_mj.series)]
    k2_issues = [i.check for i in audit_legacy(res_k2.scenario, res_k2.metrics, res_k2.series)]

    # 2. Stored-air windless propulsion vs uncharged control
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
    charged_doc = {
        **uncharged_doc,
        "pneumatics": {
            **uncharged_doc["pneumatics"],
            "precharge_pa": 350_000.0,
        },
    }
    res_charged = run(charged_doc, backend="mujoco")

    # 3. Water feeler and storm anchor reflexes
    reflex_doc = {
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
    res_reflex = run(reflex_doc, backend="mujoco")

    out = {
        "experiment": "H3-02 closed-loop pneumatic-mechanical coupling",
        "date": "2026-11-04",
        "charging_mujoco": {
            "pneumatics": res_mj.metrics["pneumatics"],
            "mean_torque_nm": float(res_mj.metrics["mean_torque"]),
            "legacy_issues": mj_issues,
        },
        "charging_k2": {
            "pneumatics": res_k2.metrics["pneumatics"],
            "mean_torque_nm": float(res_k2.metrics["mean_torque"]),
            "legacy_issues": k2_issues,
        },
        "windless_uncharged_control": {
            "stalled": bool(res_uncharged.stalled),
            "final_psi_rad": float(res_uncharged.psi[-1]),
            "distance_m": float(res_uncharged.x[-1] - res_uncharged.x[0]),
            "pneumatics": res_uncharged.metrics["pneumatics"],
        },
        "windless_charged_propulsion": {
            "stalled": bool(res_charged.stalled),
            "final_psi_rad": float(res_charged.psi[-1]),
            "distance_m": float(res_charged.x[-1] - res_charged.x[0]),
            "pneumatics": res_charged.metrics["pneumatics"],
        },
        "reflexes": res_reflex.metrics["pneumatics"],
    }
    out_path = ROOT / "experiments" / "hardening-pneumatics-closed-loop-2026-11-04.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {out_path}")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
