"""S-01: Intervention study on why leg mass raises mean crank torque.

Baseline: P1 12-leg walker (flat ground, total mass 50 kg, crank 0.6 rad/s, 2.5 revolutions,
contact_stiffness 1e5 1/s^2, mu 1.5).

Interventions:
1. Full tube_mass_per_m sweep (0.01, 0.05, 0.12, 0.20, 0.30 kg/m) with full energy account
   (input work, contact dissipation, loop-closure dissipation, normal vs tangential contact work,
   foot impact velocity, loop violation).
2. Gravity-isolated vs Inertia-isolated interventions on the leg bars (modifying MjModel arrays
   after compile while keeping torso mass adjusted so total gravitational weight or total
   translational mass stays comparable):
   - Baseline 0.05 kg/m vs 0.20 kg/m
   - "Inertia-only": bar rotational inertia & mass scaled to 0.20 kg/m, but gravity compensated
     or torso mass fixed
   - "Weight-transfer check": fix torso_mass = 38.07 kg (the 0.12 kg/m value) and vary tube_mass_per_m
   - "Zero-gravity-on-bars" (via body_gravcomp=1 on leg bodies): isolates purely inertial/centrifugal
     and constraint-impedance effects from gravitational weight of the bars!
   - "Direct equality solref vs default mass-scaled solref": in MuJoCo, positive `solref` time
     constant scales constraint stiffness K and damping B with the body's diagonal inertia/mass!
     When `tube_mass_per_m` increases 4x (0.05 -> 0.20), the effective mass of the bar bodies at the
     `connect` loop closures and foot contacts increases 4x!

Usage: .venv/bin/python packages/sim/scripts/s01_leg_mass_study.py [experiments/s01-leg-mass-study.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import mujoco
import numpy as np

from strandbeest_sim import load_scenario, run
from strandbeest_sim.config import sim_config
from strandbeest_sim.drives import MotorDrive
from strandbeest_sim.runner import make_sim

BASE = {
    "walker": {"legs": 12, "pitch": "locked", "mass": 50.0, "tube_mass_per_m": 0.12},
    "drive": {"omega": 0.6, "ramp": 2.0},
    "run": {"revolutions": 2.5, "settle": 1.0, "record_every": 8},
    "solver": {"contact_stiffness": 1e5},
}


def merge(a: dict, b: dict) -> dict:
    out = json.loads(json.dumps(a))
    for k, v in b.items():
        if isinstance(v, dict):
            out[k] = merge(out.get(k, {}), v)
        else:
            out[k] = v
    return out


def run_detailed(cfg_dict: dict, model_hook=None) -> dict:
    """Run with optional hook on (model, data, sim) before stepping, and record detailed contact/loop stats."""
    sc = sim_config(load_scenario(cfg_dict))
    sim = make_sim(sc, "mujoco")
    be = sim.backend
    m, d = be.model, be.data
    if model_hook is not None:
        model_hook(m, d, sim)
        mujoco.mj_forward(m, d)

    drive = MotorDrive(sim)
    dt = be.timestep
    settle_steps = int(round(sc.run.settle / dt))
    for _ in range(settle_steps):
        drive.control(sim, 0.0, driving=False)
        be.step()

    psi_start = sim.psi()
    target = sc.run.revolutions * 2 * math.pi
    t = 0.0

    # We collect stats specifically over revolution 2 (psi in [2*pi, 4*pi])
    in_window = False
    e_in = e_contact = e_loops = e_fric = 0.0
    sum_tau = 0.0
    n_steps = 0
    sum_fn = 0.0
    sum_ft = 0.0
    sum_slip_weighted = 0.0
    max_loop_viol = 0.0
    sum_loop_force = 0.0
    x0 = x1 = None
    k0 = u0 = k1 = u1 = 0.0

    while sim.psi() - psi_start < target:
        drive.control(sim, t, driving=True)
        be.step()
        t += dt
        psi_rel = sim.psi() - psi_start

        if psi_rel >= 2 * math.pi and not in_window:
            in_window = True
            x0 = be.body_position("torso")[0]
            en0 = be.energies()
            k0, u0 = en0.kinetic, en0.potential

        if in_window and psi_rel <= 4 * math.pi:
            omega = -sc.walker.direction * be.joint_velocity(sim.info.crank_joint)
            tau = drive.torque(sim)
            pb = be.power_balance()
            e_in += tau * omega * dt
            e_contact += pb.contact * dt
            e_loops += pb.equality * dt
            e_fric += (pb.joint_friction + pb.viscous) * dt
            sum_tau += tau
            n_steps += 1

            loads = be.foot_loads()
            fn_step = sum(f.normal for f in loads)
            ft_step = sum(f.tangent for f in loads)
            slip_step = sum(f.tangent * f.slip for f in loads)
            sum_fn += fn_step
            sum_ft += ft_step
            sum_slip_weighted += slip_step * dt

            viol = be.loop_residual()
            max_loop_viol = max(max_loop_viol, viol)
            if d.ne:
                sum_loop_force += float(np.linalg.norm(d.efc_force[: d.ne]))

            x1 = be.body_position("torso")[0]
            en1 = be.energies()
            k1, u1 = en1.kinetic, en1.potential

    d_mech = (k1 + u1) - (k0 + u0)
    stride = (x1 - x0) if (x0 is not None and x1 is not None) else float("nan")
    mean_tau = sum_tau / max(1, n_steps)
    implied_tau = e_in / (2 * math.pi)
    return {
        "stride_per_rev": round(stride, 5),
        "mean_torque_Nm": round(mean_tau, 4),
        "implied_torque_from_work_Nm": round(implied_tau, 4),
        "work_in_J": round(e_in, 4),
        "work_contact_J": round(e_contact, 4),
        "work_loops_J": round(e_loops, 4),
        "work_mech_delta_J": round(d_mech, 4),
        "work_residual_J": round(e_in - e_contact - e_loops - e_fric - d_mech, 4),
        "contact_share": round(e_contact / e_in, 4) if e_in else 0.0,
        "loops_share": round(e_loops / e_in, 4) if e_in else 0.0,
        "mean_total_normal_N": round(sum_fn / max(1, n_steps), 3),
        "mean_total_tangent_N": round(sum_ft / max(1, n_steps), 3),
        "tangent_slip_integral_J": round(sum_slip_weighted, 4),
        "max_loop_violation_mm": round(max_loop_viol * 1000, 4),
        "mean_loop_force_norm_N": round(sum_loop_force / max(1, n_steps), 3),
        "bar_mass_total_kg": round(sim.info.bar_mass_total, 3),
        "torso_mass_kg": round(float(m.body_mass[1]), 3),
    }


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("experiments/s01-leg-mass-study.json")

    print("=== Part 1: Tube mass sweep with full energy & contact decomposition ===", flush=True)
    sweep = {}
    for tm in (0.02, 0.05, 0.12, 0.20, 0.30):
        res = run_detailed(merge(BASE, {"walker": {"tube_mass_per_m": tm}}))
        sweep[str(tm)] = res
        print(f"  tube_mass={tm:4.2f} kg/m | mean_tau={res['mean_torque_Nm']:6.3f} N·m | "
              f"W_in={res['work_in_J']:6.2f} J (contact={res['work_contact_J']:6.2f} J, loops={res['work_loops_J']:5.2f} J) | "
              f"F_n={res['mean_total_normal_N']:6.1f} N, F_t={res['mean_total_tangent_N']:5.2f} N | "
              f"loop_F={res['mean_loop_force_norm_N']:6.1f} N, viol={res['max_loop_violation_mm']:5.3f} mm", flush=True)

    print("\n=== Part 2: Controlled Interventions (comparing 0.05 vs 0.20 kg/m) ===", flush=True)
    interventions = {}

    def record_int(name: str, cfg: dict, hook=None):
        r = run_detailed(cfg, hook)
        interventions[name] = r
        print(f"  {name:36s} -> mean_tau={r['mean_torque_Nm']:6.3f} N·m | W_in={r['work_in_J']:6.2f} J "
              f"(contact={r['work_contact_J']:6.2f} J, loops={r['work_loops_J']:5.2f} J) | "
              f"F_t={r['mean_total_tangent_N']:5.2f} N | loop_F={r['mean_loop_force_norm_N']:6.1f} N", flush=True)

    # 1. Baseline 0.05 and 0.20 (already in sweep)
    interventions["base_0.05"] = sweep["0.05"]
    interventions["base_0.20"] = sweep["0.2"]

    # 2. Intervention A: Gravity compensation on leg bars ONLY (bars have 0.20 or 0.05 mass/inertia, but weightless in gravity;
    # torso carries full 50 kg so total ground reaction weight = 50*g in both!)
    def hook_gravcomp_bars_50kg_torso(m, d, sim):
        m.body_mass[1] = 50.0
        for b in range(2, m.nbody):
            m.body_gravcomp[b] = 1.0

    record_int("gravcomp_bars_0.05", merge(BASE, {"walker": {"tube_mass_per_m": 0.05}}), hook_gravcomp_bars_50kg_torso)
    record_int("gravcomp_bars_0.20", merge(BASE, {"walker": {"tube_mass_per_m": 0.20}}), hook_gravcomp_bars_50kg_torso)

    # 3. Intervention B: Take 0.05 kg/m model, keep bar masses at 0.05 kg/m, ONLY scale bar rotational inertia `body_inertia` by 4x (to match 0.20)
    def hook_scale_bar_inertia_4x(m, d, sim):
        for b in range(2, m.nbody):
            m.body_inertia[b] *= 4.0

    record_int("only_rot_inertia_4x_from_0.05", merge(BASE, {"walker": {"tube_mass_per_m": 0.05}}), hook_scale_bar_inertia_4x)

    # 4. Intervention C: Take 0.20 kg/m model, freeze `body_invweight0` and `dof_invweight0` to the 0.05 kg/m values!
    sim_005 = make_sim(sim_config(load_scenario(merge(BASE, {"walker": {"tube_mass_per_m": 0.05}}))), "mujoco")
    bw0_005 = sim_005.backend.model.body_invweight0.copy()
    dw0_005 = sim_005.backend.model.dof_invweight0.copy()

    def hook_freeze_invweight0_to_005(m, d, sim):
        m.body_invweight0[:] = bw0_005
        m.dof_invweight0[:] = dw0_005

    record_int("mass_0.20_with_invweight0_of_0.05", merge(BASE, {"walker": {"tube_mass_per_m": 0.20}}), hook_freeze_invweight0_to_005)

    # 5. Intervention D: Take 0.05 kg/m model, set `body_invweight0` and `dof_invweight0` to the 0.20 kg/m values!
    sim_020 = make_sim(sim_config(load_scenario(merge(BASE, {"walker": {"tube_mass_per_m": 0.20}}))), "mujoco")
    bw0_020 = sim_020.backend.model.body_invweight0.copy()
    dw0_020 = sim_020.backend.model.dof_invweight0.copy()

    def hook_freeze_invweight0_to_020(m, d, sim):
        m.body_invweight0[:] = bw0_020
        m.dof_invweight0[:] = dw0_020

    record_int("mass_0.05_with_invweight0_of_0.20", merge(BASE, {"walker": {"tube_mass_per_m": 0.05}}), hook_freeze_invweight0_to_020)

    # 6. Intervention E: Slower speed (omega = 0.2 rad/s instead of 0.6 rad/s, reducing omega^2 inertial acceleration 9x)
    record_int("slow_omega_0.20_mass_0.05", merge(BASE, {"walker": {"tube_mass_per_m": 0.05}, "drive": {"omega": 0.2, "ramp": 1.0}}))
    record_int("slow_omega_0.20_mass_0.20", merge(BASE, {"walker": {"tube_mass_per_m": 0.20}, "drive": {"omega": 0.2, "ramp": 1.0}}))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"sweep": sweep, "interventions": interventions}, indent=2) + "\n")
    print(f"\nSaved to {out_path}", flush=True)


if __name__ == "__main__":
    main()
