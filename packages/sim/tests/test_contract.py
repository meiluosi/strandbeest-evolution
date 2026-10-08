"""E4-03: the backend contract suite passes for the MuJoCo adapter, and catches deliberately broken backends."""

import pytest
from strandbeest_sim.backend import PhysicsBackend
from strandbeest_sim.backends.mujoco_backend import MujocoBackend
from strandbeest_sim.contract import CHECKS, run_contract


@pytest.mark.parametrize("name", list(CHECKS))
def test_mujoco_adapter_passes(name):
    CHECKS[name](MujocoBackend)


def test_the_adapter_implements_the_protocol():
    b = MujocoBackend()
    b.build_reference("pendulum")
    assert isinstance(b, PhysicsBackend)


# ---- mutants: bugs the suite must catch ---------------------------------------------------------------------------
class ReversedGravity(MujocoBackend):
    """Gravity points up."""

    def build_reference(self, kind, **params):
        if "gravity" in params:
            params["gravity"] = -params["gravity"]
        super().build_reference(kind, **params)

    def set_param(self, path, value):
        if path == "gravity":
            value = tuple(-v for v in value)
        super().set_param(path, value)


class KineticOnlyEnergy(MujocoBackend):
    """energies() forgets the potential energy."""

    def energies(self):
        from strandbeest_sim.backend import Energies

        e = super().energies()
        return Energies(kinetic=e.kinetic, potential=0.0)


class SlowClock(MujocoBackend):
    """The reported timestep is wrong by 10 %."""

    @property
    def timestep(self):
        return super().timestep * 1.1


class ForgetfulRestore(MujocoBackend):
    """restore() does not bring back the velocities."""

    def restore(self, snap):
        super().restore(snap)
        self.data.qvel[:] = 0.0


class UnitBug(MujocoBackend):
    """Bar mass is taken per length *unit* instead of per metre: it depends on how the lengths were written down."""

    def build(self, cfg, plan):
        cfg = cfg.model_copy(deep=True)
        cfg.walker.tube_mass_per_m = cfg.walker.tube_mass_per_m * cfg.walker.unit / 0.002
        return super().build(cfg, plan)


@pytest.mark.parametrize(
    "mutant,must_fail",
    [
        (ReversedGravity, {"gravity_direction", "incline_acceleration", "pendulum_period"}),
        (KineticOnlyEnergy, {"energy_conservation"}),
        (SlowClock, {"pendulum_period"}),
        (ForgetfulRestore, {"snapshot_restore"}),
        (UnitBug, {"unit_scaling"}),
    ],
)
def test_the_suite_catches_a_broken_backend(mutant, must_fail):
    result = run_contract(mutant)
    failed = {k for k, v in result.items() if v is not None}
    assert must_fail <= failed, f"{mutant.__name__}: expected {must_fail} to fail, got {failed}"
