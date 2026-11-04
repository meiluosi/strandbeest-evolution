"""H1-01: branching isolates physical parameters as well as integration state."""

import numpy as np
import pytest
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design
from strandbeest_sim.interactive import InteractiveSession


DESIGN = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")


def session(overrides=None):
    return InteractiveSession.create(scenario_from_design(DESIGN, overrides))


@pytest.mark.parametrize(
    "path,value,read",
    [
        ("gravity", (0.0, 0.0, -1.62), lambda s: s.be.model.opt.gravity),
        ("contact.softness", (50000.0, 300.0), lambda s: s.be.model.geom_solref),
        ("terrain.friction", 0.45, lambda s: s.be.model.geom_friction),
    ],
)
@pytest.mark.parametrize("edit_parent", [False, True], ids=["edit_child", "edit_parent"])
def test_fork_parameter_edits_do_not_change_parent_or_siblings(path, value, read, edit_parent):
    parent = session()
    parent.step(200)
    child = parent.fork()
    sibling = parent.fork()
    grandchild = child.fork()
    branches = [parent, child, sibling, grandchild]
    before = [read(branch).copy() for branch in branches]
    edited = parent if edit_parent else child

    edited.set_param(path, value)

    for branch, original in zip(branches, before):
        if branch is edited:
            assert not np.array_equal(read(branch), original)
        else:
            np.testing.assert_array_equal(read(branch), original)
    if path == "terrain.friction":
        assert edited.sc.terrain.friction == value
        assert all(branch.sc.terrain.friction != value for branch in branches if branch is not edited)

    # The unedited branches must still evolve identically, not merely report
    # unchanged settings while referring to different hidden integration state.
    unchanged = [branch for branch in branches if branch is not edited]
    expected = unchanged[0].step(400)
    for branch in unchanged[1:]:
        assert branch.step(400) == expected
        np.testing.assert_array_equal(branch.be.data.qpos, unchanged[0].be.data.qpos)
        np.testing.assert_array_equal(branch.be.data.qvel, unchanged[0].be.data.qvel)


def test_fork_inherits_live_parameters_without_rebuilding_default_world():
    parent = session()
    parent.set_param("gravity", (0.0, 0.0, -1.62))
    parent.set_param("contact.softness", (50000.0, 300.0))
    parent.set_param("terrain.friction", 0.45)
    parent.step(200)
    child = parent.fork()

    np.testing.assert_array_equal(child.be.model.opt.gravity, parent.be.model.opt.gravity)
    np.testing.assert_array_equal(child.be.model.geom_solref, parent.be.model.geom_solref)
    np.testing.assert_array_equal(child.be.model.geom_friction, parent.be.model.geom_friction)
    assert child.step(400) == parent.step(400)
    np.testing.assert_array_equal(child.be.data.qpos, parent.be.data.qpos)


def test_sail_fork_releasing_its_motor_does_not_release_parent_or_sibling():
    parent = session({"drive": {"kind": "sail"}})
    child = parent.fork()
    sibling = parent.fork()
    gains = parent.be.model.actuator_gainprm.copy()
    biases = parent.be.model.actuator_biasprm.copy()
    assert np.any(gains)

    child.step(1)  # First sail step releases its settling servo in MjModel.

    assert child.drive.released
    assert not np.any(child.be.model.actuator_gainprm)
    for branch in (parent, sibling):
        assert not branch.drive.released
        np.testing.assert_array_equal(branch.be.model.actuator_gainprm, gains)
        np.testing.assert_array_equal(branch.be.model.actuator_biasprm, biases)


@pytest.mark.parametrize("drive_kind", ["motor", "sail"])
def test_fork_preserves_drive_state_and_snapshot_restore_continuation(drive_kind):
    parent = session({"drive": {"kind": drive_kind}})
    parent.step(200)
    parent.pause()
    child = parent.fork()
    assert child.paused
    assert child.step(10) == parent.step(10)

    parent.resume()
    child.resume()
    saved = child.snapshot()
    expected = parent.step(400)
    assert child.step(400) == expected
    np.testing.assert_array_equal(child.be.data.qpos, parent.be.data.qpos)
    child.restore(saved)
    assert child.step(400) == expected
    np.testing.assert_array_equal(child.be.data.qpos, parent.be.data.qpos)


@pytest.mark.parametrize("drive_kind", ["motor", "sail"])
@pytest.mark.parametrize("wind_kind", ["constant", "gusts", "turbulent", "profile_turbulent"])
def test_snapshot_restores_world_parameters_and_repeats_the_original_trajectory(drive_kind, wind_kind):
    current = session({"drive": {"kind": drive_kind, "ramp": 0},
                       "wind": {"kind": wind_kind, "speed": 3.0, "params": {"seed": 17}}})
    current.step(600)  # Populate the lazy turbulence buffer past its first sample.
    original_config = current.sc.model_dump()
    saved = current.snapshot()
    reference = current.fork()
    expected = reference.step(800)

    for _ in range(2):  # Reusing a checkpoint must not mutate the checkpoint itself.
        current.set_param("gravity", (0.0, 0.0, -1.62))
        current.set_param("contact.softness", (50000.0, 300.0))
        current.set_param("terrain.friction", 3.0)
        current.set_param("wind.speed", 12.0)
        current.set_param("wind.direction", 60.0)
        current.set_param("drive.omega", 4.0)
        current.step(300)
        current.pause()
        current.restore(saved)

        assert not current.paused
        assert current.sc.model_dump() == original_config
        np.testing.assert_array_equal(current.be.model.opt.gravity, reference.be.model.opt.gravity)
        np.testing.assert_array_equal(current.be.model.geom_solref, reference.be.model.geom_solref)
        np.testing.assert_array_equal(current.be.model.geom_friction, reference.be.model.geom_friction)
        assert current.step(800) == expected
        np.testing.assert_array_equal(current.be.data.qpos, reference.be.data.qpos)
        np.testing.assert_array_equal(current.be.data.qvel, reference.be.data.qvel)


def test_restore_before_sail_release_reinstates_the_settling_servo():
    current = session({"drive": {"kind": "sail"}, "wind": {"speed": 3.0}})
    current.pause()
    saved = current.snapshot()
    reference = current.fork()
    gain = current.be.model.actuator_gainprm.copy()
    bias = current.be.model.actuator_biasprm.copy()
    assert np.any(gain)
    current.resume()
    current.step(200)
    assert current.drive.released
    assert not np.any(current.be.model.actuator_gainprm)

    current.restore(saved)

    assert current.paused
    assert not current.drive.released
    np.testing.assert_array_equal(current.be.model.actuator_gainprm, gain)
    np.testing.assert_array_equal(current.be.model.actuator_biasprm, bias)
    assert current.step(0) == reference.step(0)
    current.resume()
    reference.resume()
    assert current.step(400) == reference.step(400)
    np.testing.assert_array_equal(current.be.data.qpos, reference.be.data.qpos)


def test_live_wind_edit_changes_the_actual_sail_force_before_restore():
    current = session({"drive": {"kind": "sail"}, "wind": {"kind": "constant", "speed": 3.0}})
    saved = current.snapshot()
    current.set_param("wind.speed", 6.0)
    assert current.drive.wind(0.0) == pytest.approx(6.0)
    current.set_param("wind.direction", 60.0)
    assert current.drive.wind(0.0) == pytest.approx(3.0)
    current.restore(saved)
    assert current.drive.wind(0.0) == pytest.approx(3.0)
    assert current.sc.wind.params.get("yaw_deg", 0.0) == 0.0


def test_k2_session_snapshot_restores_parameters_and_drive_state():
    sc = scenario_from_design(DESIGN, {"drive": {"kind": "sail"}, "wind": {"speed": 3.0}})
    current = InteractiveSession.create(sc, backend="k2")
    current.step(200)
    saved = current.snapshot()
    reference = current.fork()
    current.set_param("gravity", (0.0, 0.0, -1.62))
    current.set_param("terrain.friction", 0.3)
    current.set_param("wind.speed", 6.0)
    current.step(100)
    current.restore(saved)
    assert current.sc.model_dump() == reference.sc.model_dump()
    assert current.step(400) == reference.step(400)
    np.testing.assert_array_equal(current.be._q, reference.be._q)
    np.testing.assert_array_equal(current.be._v, reference.be._v)
