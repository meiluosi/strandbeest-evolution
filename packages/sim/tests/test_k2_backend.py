"""Tests for the K2 independent planar rigid-body physics backend (ADR-0010, V-02)."""

import sys
import pytest
from strandbeest_sim.backend import PhysicsBackend
from strandbeest_sim.backends import make_backend
from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.contract import CHECKS

K2_REFERENCE_CHECKS = [
    "energy_conservation",
    "pendulum_period",
    "incline_acceleration",
    "gravity_direction",
    "snapshot_restore",
    "determinism",
]


def test_k2_does_not_import_mujoco():
    """V-02 requirement: K2 must be an independent implementation and must not import MuJoCo."""
    import inspect
    import strandbeest_sim.backends.k2_backend as k2_module

    source = inspect.getsource(k2_module)
    assert "import mujoco" not in source
    assert "from mujoco" not in source


def test_k2_implements_protocol():
    b = make_backend("k2")
    b.build_reference("pendulum")
    assert isinstance(b, PhysicsBackend)
    assert b.name == "k2"


@pytest.mark.parametrize("name", K2_REFERENCE_CHECKS)
def test_k2_passes_reference_contract_checks(name):
    CHECKS[name](K2Backend)


# ---- Mutants: test that bugs in K2 are caught by the contract suite ----
class K2ReversedGravity(K2Backend):
    def set_param(self, path, value):
        if path == "gravity":
            value = tuple(-v for v in value)
        super().set_param(path, value)


class K2KineticOnly(K2Backend):
    def energies(self):
        from strandbeest_sim.backend import Energies
        e = super().energies()
        return Energies(kinetic=e.kinetic, potential=0.0)


def test_k2_catches_reversed_gravity():
    with pytest.raises(AssertionError):
        CHECKS["incline_acceleration"](K2ReversedGravity)


def test_k2_catches_missing_potential_energy():
    with pytest.raises(AssertionError):
        CHECKS["energy_conservation"](K2KineticOnly)
