"""H2-01 diagnostic: constant-force analytic check of post-step energy accounting.

This isolates time alignment. It does not claim to explain all walker residuals.
Usage: .venv/bin/python packages/sim/scripts/hardening_g1_energy_timing.py out.json
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import mujoco


def main() -> None:
    out = Path(sys.argv[1])
    rows = []
    for dt in (0.1, 0.01, 0.001):
        for steps in (1, 10):
            model = mujoco.MjModel.from_xml_string(
                f'<mujoco><option timestep="{dt}" gravity="0 0 0" integrator="implicitfast">'
                '<flag energy="enable"/></option><worldbody><body>'
                '<joint name="x" type="slide" axis="1 0 0"/>'
                '<geom type="sphere" size="0.1" mass="1"/></body></worldbody>'
                '<actuator><motor joint="x"/></actuator></mujoco>'
            )
            data = mujoco.MjData(model)
            data.ctrl[0] = 1.0
            rectangle = midpoint = 0.0
            for _ in range(steps):
                before = float(data.qvel[0])
                mujoco.mj_step(model, data)
                after = float(data.qvel[0])
                force = float(data.actuator_force[0])
                rectangle += force * after * dt
                midpoint += force * (before + after) / 2 * dt
            analytic_ke = 0.5 * (steps * dt) ** 2
            assert math.isclose(midpoint, analytic_ke, rel_tol=1e-12)
            assert math.isclose(0.5 * float(data.qvel[0]) ** 2, analytic_ke, rel_tol=1e-12)
            rows.append({
                "dt_s": dt,
                "steps": steps,
                "mass_kg": 1,
                "force_n": 1,
                "analytic_kinetic_j": analytic_ke,
                "post_step_rectangle_work_j": rectangle,
                "midpoint_velocity_work_j": midpoint,
                "data_energy_immediately_after_step_j": float(data.energy[1]),
            })
    report = {
        "evidence_level": "E0",
        "scope": "Constant force, one DOF; no claim that this explains every full-walker residual",
        "documentation": "https://mujoco.readthedocs.io/en/stable/computation/#consistency-in-mjdata",
        "mujoco_version": mujoco.__version__,
        "rows": rows,
    }
    with out.open("x") as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write("\n")
    print(f"{len(rows)} analytic cases confirmed; evidence: {out}")


if __name__ == "__main__":
    main()
