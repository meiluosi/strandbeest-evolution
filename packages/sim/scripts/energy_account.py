"""Energy accounting of a motor-driven walk: where does the input work go?  (glass-box feasibility probe)

Input power  = servo torque * crank speed.
Dissipated by contacts = - sum over contact constraint rows of (constraint force * constraint-space velocity)
  (a friction facet that opposes slip has force*velocity < 0, so this is positive; the same sum covers normal damping).
Dissipated by loop constraints and joint friction are accumulated the same way for comparison.
Per revolution, kinetic and potential energy are periodic, so input work should equal total dissipation.

Usage: python scripts/energy_account.py [design.json]
"""

from __future__ import annotations

import math
import sys

import mujoco
import numpy as np

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design
from strandbeest_sim.drives import MotorDrive
from strandbeest_sim.runner import make_sim


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else schema_dir() / "examples" / "design-jansen-small-6leg.json"
    design = Design.load(path)
    sim = make_sim(scenario_from_design(design, {"run": {"settle": 0.5}}))
    m, d = sim.model, sim.data
    drive, dt = MotorDrive(sim), m.opt.timestep
    contact_types = (mujoco.mjtConstraint.mjCNSTR_CONTACT_FRICTIONLESS, mujoco.mjtConstraint.mjCNSTR_CONTACT_PYRAMIDAL, mujoco.mjtConstraint.mjCNSTR_CONTACT_ELLIPTIC)
    for _ in range(int(0.5 / dt)):
        drive.control(sim, 0.0, False)
        mujoco.mj_step(m, d)
    psi0, t = sim.psi(), 0.0
    e_in = e_contact = e_loops = e_fric = 0.0
    marks = []  # (psi, cumulative energies) at the start of each full revolution after the first
    next_mark = 2 * math.pi
    while sim.psi() - psi0 < 3 * 2 * math.pi + 1e-9:
        drive.control(sim, t, True)
        mujoco.mj_step(m, d)
        t += dt
        omega = -sim.scenario.walker.direction * float(d.qvel[sim.crank_dofadr])
        e_in += drive.torque(sim) * omega * dt
        if d.nefc:
            p = d.efc_force[: d.nefc] * d.efc_vel[: d.nefc]
            kinds = d.efc_type[: d.nefc]
            e_contact -= float(p[np.isin(kinds, contact_types)].sum()) * dt
            e_loops -= float(p[kinds == mujoco.mjtConstraint.mjCNSTR_EQUALITY].sum()) * dt
            e_fric -= float(p[kinds == mujoco.mjtConstraint.mjCNSTR_FRICTION_DOF].sum()) * dt
        if sim.psi() - psi0 >= next_mark and len(marks) < 3:
            marks.append((e_in, e_contact, e_loops, e_fric))
            next_mark += 2 * math.pi
    # revolutions 2 and 3 (the first one contains the start-up ramp)
    a, b = np.array(marks[0]), np.array(marks[-1])
    revs = len(marks) - 1
    d_in, d_con, d_loop, d_fric = (b - a) / revs
    total = d_con + d_loop + d_fric
    print(f"per revolution (average over {revs}):")
    print(f"  work put in by the crank servo : {d_in * 1000:8.3f} mJ")
    print(f"  dissipated at the contacts      : {d_con * 1000:8.3f} mJ  ({d_con / d_in * 100:.0f} % of input)")
    print(f"  dissipated in the loop closures : {d_loop * 1000:8.3f} mJ  ({d_loop / d_in * 100:.0f} %)")
    print(f"  dissipated by joint friction    : {d_fric * 1000:8.3f} mJ  ({d_fric / d_in * 100:.0f} %)")
    print(f"  unaccounted (kinetic/potential not exactly periodic, integrator error): {(d_in - total) * 1000:8.3f} mJ ({(d_in - total) / d_in * 100:.0f} %)")
    print(f"  mean crank torque implied by the input work: {d_in / (2 * math.pi) * 1000:.3f} mN·m")


if __name__ == "__main__":
    main()
