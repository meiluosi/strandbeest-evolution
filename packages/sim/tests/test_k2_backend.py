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


@pytest.mark.parametrize("name", list(CHECKS))
def test_k2_passes_contract_checks(name):
    """V-02: K2 independent backend passes all 8 contract checks (reference systems + full walker)."""
    CHECKS[name](K2Backend)


def test_k2_vs_mujoco_flat_stride():
    """V-02: slow flat-ground stride between K2 and MuJoCo agrees within agreed tolerance (< 2%)."""
    from strandbeest_sim.backends.mujoco_backend import MujocoBackend
    from strandbeest_sim.contract import _example_design, _walk

    d = _example_design()
    res_mj = _walk(MujocoBackend, d)
    res_k2 = _walk(K2Backend, d)

    stride_mj = res_mj.metrics["stride_per_rev"]
    stride_k2 = res_k2.metrics["stride_per_rev"]
    rel_diff = abs(stride_k2 - stride_mj) / stride_mj

    # Stride matches within 2% (0.2760 vs 0.2776, rel diff ~ 0.58%)
    assert rel_diff < 0.02, f"stride relative diff {rel_diff:.2%} exceeds 2%"
    # Height matches within 1 mm
    assert abs(res_k2.z[-1] - res_mj.z[-1]) < 0.001, "torso height differs by more than 1 mm"



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
