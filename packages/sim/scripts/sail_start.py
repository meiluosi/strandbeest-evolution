"""Lowest wind speed at which the small printed walker starts by itself under a sail drive (MuJoCo), compared with the
prediction from its own motor-driven peak torque:  w_min = sqrt(2 (tau_peak + friction) / (gear rho Cd A r)).

Usage: python scripts/sail_start.py out.json
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design

WINDS = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2]


def design() -> Design:
    return Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")


def one(w: float) -> dict:
    ov = {"drive": {"kind": "sail"}, "wind": {"speed": w}, "run": {"revolutions": 1.0, "settle": 0.5, "give_up_after": 10, "max_time": 40, "frame_rate": 0}}
    r = run(scenario_from_design(design(), ov))
    return {"wind": w, "completed_one_revolution": not r.stalled, "time_s": float(r.t[-1]), "distance_m": float(r.x[-1] - r.x[0]),
            "valid": bool(r.metrics["max_loop_violation"] < 0.0017)}


def main() -> None:
    d = design()
    motor = run(scenario_from_design(d, {"run": {"revolutions": 2.0, "settle": 0.5, "frame_rate": 0}}))
    sc = scenario_from_design(d)
    dr = sc.drive
    k = dr.sail_gear * 1.2 * dr.sail_drag_coeff * dr.sail_area * dr.sail_radius
    peak = float(motor.metrics["peak_torque"])
    predicted = math.sqrt(2 * (peak + dr.crank_friction) / k)
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(one, WINDS))
    out = {"motor_peak_torque_nm": peak, "crank_friction_nm": dr.crank_friction, "predicted_start_wind_m_s": predicted, "rows": rows}
    json.dump(out, open(sys.argv[1], "w"), indent=2)
    print(f"motor-driven peak torque {peak * 1000:.1f} mN·m -> predicted start wind {predicted:.2f} m/s")
    for r in rows:
        print(f"  wind {r['wind']:.1f} m/s: one revolution {'yes' if r['completed_one_revolution'] else 'NO '}  ({r['time_s']:.1f} s, {r['distance_m'] * 1000:.0f} mm){'' if r['valid'] else '  [loops opened: not trusted]'}")


if __name__ == "__main__":
    main()
