"""W-02: pin friction and damping are named assumptions (default 0 = ideal); they act on every linkage pin and the energy account sees them."""

import mujoco

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.runner import make_sim

DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
SAIL = {"drive": {"kind": "sail"}, "wind": {"speed": 3.0}, "run": {"revolutions": 0.5, "settle": 0.3, "give_up_after": 5, "max_time": 20, "frame_rate": 0}}


def sc(walker=None, **ov):
    out = {k: dict(v) for k, v in ov.items()}
    if walker:
        out["walker"] = walker
    return scenario_from_design(DESIGN, out)


def pin_dofs(sim):
    m = sim.backend.model
    names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) for j in range(m.njnt)]
    return [m.jnt_dofadr[j] for j, n in enumerate(names) if n and not n.startswith(("crank", "t"))], m


def test_zero_is_the_default_and_leaves_the_model_ideal():
    sim = make_sim(sc(**SAIL))
    dofs, m = pin_dofs(sim)
    assert dofs and all(m.dof_frictionloss[d] == 0 and m.dof_damping[d] == 0 for d in dofs)


def test_values_reach_every_linkage_pin_but_not_the_crank_or_the_torso():
    sim = make_sim(sc({"joint_friction": 0.001, "joint_damping": 0.0005}, **SAIL))
    dofs, m = pin_dofs(sim)
    assert all(m.dof_frictionloss[d] == 0.001 and m.dof_damping[d] == 0.0005 for d in dofs)
    crank = m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "crank0")]
    assert m.dof_frictionloss[crank] != 0.001  # the crank has its own parameters in the drive
    assert m.dof_damping[0] == 0 and m.dof_frictionloss[0] == 0  # torso slide


def crank_speed(r):
    return float((r.psi[-1] - r.psi[0]) / (r.t[-1] - r.t[0]))


def test_pin_losses_slow_the_sail_driven_crank_and_the_account_still_closes():
    ideal = run(sc(**SAIL))
    lossy = run(sc({"joint_friction": 0.001, "joint_damping": 0.0005}, **SAIL))
    assert crank_speed(lossy) < crank_speed(ideal)
    assert abs(lossy.metrics["energy_residual_share"]) < 0.02
    assert lossy.metrics["energy_friction_share"] > ideal.metrics["energy_friction_share"]  # the pins dissipate part of the input
