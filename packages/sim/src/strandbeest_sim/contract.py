"""The backend contract suite (ADR-0005, E4-03). Every physics backend must pass these checks.

Each check takes a zero-argument factory that returns a fresh, unbuilt backend and raises AssertionError when the backend
misbehaves. They are plain functions so a third-party backend can run them (`run_contract(factory)`) and so the tests can run
them against deliberately broken backends and require that they fail (tests/test_contract.py).

  energy_conservation     a frictionless pendulum keeps its total energy (energies())
  pendulum_period         small swings take 2*pi*sqrt(L/g) (analytic)
  incline_acceleration    a block on a tilted plane accelerates at g*(sin a - mu*cos a) (analytic; set_param("gravity"))
  gravity_direction       a dropped block falls down, not up
  snapshot_restore        restore + step equals stepping on without the detour (bit for bit)
  determinism             two identical runs give identical results (bit for bit)
  mirror_symmetry         the mirrored walker (strandbeest_common.ops mirror) walks the mirror-image path
  unit_scaling            the same physical walker written in other length units behaves identically
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

import numpy as np

from .backend import PhysicsBackend

Factory = Callable[[], PhysicsBackend]
G = 9.81


def _pendulum(make: Factory, angle: float = 0.05, length: float = 1.0) -> PhysicsBackend:
    b = make()
    b.build_reference("pendulum", length=length, angle=angle, gravity=G)
    return b


def check_energy_conservation(make: Factory) -> None:
    b = _pendulum(make, angle=0.6)
    e0 = b.energies().total
    swing = abs(e0 - b.energies().potential) + 1.0  # scale: the energy exchanged in a swing is about m*g*L*(1-cos(angle))
    scale = G * 1.0 * (1 - math.cos(0.6))
    worst = 0.0
    for _ in range(int(5.0 / b.timestep)):
        b.step()
        worst = max(worst, abs(b.energies().total - e0))
    assert worst < 0.01 * scale, f"total energy drifted by {worst / scale:.2%} of the swing energy"
    assert swing > 0


def check_pendulum_period(make: Factory) -> None:
    b = _pendulum(make)
    th = []
    for _ in range(int(10.0 / b.timestep)):
        b.step()
        th.append(b.joint_position("hinge"))
    crossings = [i for i in range(1, len(th)) if th[i - 1] > 0 >= th[i]]
    assert len(crossings) >= 3, "the pendulum does not swing"
    period = float(np.mean(np.diff(crossings))) * b.timestep
    expected = 2 * math.pi * math.sqrt(1.0 / G)
    assert abs(period - expected) / expected < 0.005, f"period {period:.4f} s, expected {expected:.4f} s"


def check_incline_acceleration(make: Factory) -> None:
    mu, a = 0.2, math.radians(30)
    b = make()
    b.build_reference("block", mass=1.0, friction=mu)
    b.set_param("gravity", (-G * math.sin(a), 0.0, -G * math.cos(a)))  # uphill = +x
    b.step(int(0.2 / b.timestep))
    b.step(int(0.2 / b.timestep))
    x = b.body_position("block")[0]
    est = -2 * x / 0.4**2
    expected = G * (math.sin(a) - mu * math.cos(a))
    assert abs(est - expected) / expected < 0.03, f"acceleration {est:.3f} m/s^2, expected {expected:.3f}"


def check_gravity_direction(make: Factory) -> None:
    b = make()
    b.build_reference("block", mass=1.0, friction=0.5)
    z0 = b.body_position("block")[2]
    b.set_param("gravity", (0.0, 0.0, -G))
    b.step(int(0.2 / b.timestep))
    assert abs(b.body_position("block")[2] - z0) < 0.01, "a block resting on the plane moved vertically"
    b = _pendulum(make, angle=0.5)
    b.step(int(0.3 / b.timestep))
    assert b.joint_position("hinge") < 0.5, "a pendulum held to the side must fall toward hanging down"


def check_snapshot_restore(make: Factory) -> None:
    b = _pendulum(make, angle=0.4)
    b.step(300)
    snap = b.snapshot()
    b.step(500)
    a = (b.joint_position("hinge"), b.joint_velocity("hinge"), b.time)
    b.restore(snap)
    b.step(500)
    assert (b.joint_position("hinge"), b.joint_velocity("hinge"), b.time) == a, "restore + step differs from stepping on"


def check_determinism(make: Factory) -> None:
    out = []
    for _ in range(2):
        b = _pendulum(make, angle=0.4)
        b.step(1000)
        out.append((b.joint_position("hinge"), b.joint_velocity("hinge"), b.energies().total))
    assert out[0] == out[1], "the same input gave different results"


def _scenario(design: dict, overrides: dict | None = None):
    from strandbeest_common import Design

    from .from_design import scenario_from_design

    ov = {"run": {"revolutions": 0.6, "settle": 0.3, "frame_rate": 0}, **(overrides or {})}
    return scenario_from_design(Design(design), ov)


def _walk(make: Factory, design: dict, overrides: dict | None = None):
    from .runner import run

    return run(_scenario(design, overrides), backend=make())


def _example_design() -> dict:
    root = Path(__file__).resolve()
    for p in root.parents:
        f = p / "schemas" / "examples" / "design-jansen-small-6leg.json"
        if f.exists():
            return json.loads(f.read_text())
    raise FileNotFoundError("schemas/examples/design-jansen-small-6leg.json")


def check_mirror_symmetry(make: Factory) -> None:
    from strandbeest_common.ops import apply_op, make_op

    d = _example_design()
    mirrored = apply_op(d, make_op("mirror", {})).design
    a, b = _walk(make, d), _walk(make, mirrored)
    assert a.x[-1] - a.x[0] > 0.05, "the reference walker does not walk forward"
    span = float(np.ptp(a.x))
    assert float(np.max(np.abs(b.x + a.x))) < 0.02 * span, "the mirrored walker does not walk the mirror-image path"
    assert float(np.max(np.abs(b.z - a.z))) < 5e-4, "mirroring changed the body height"


def check_unit_scaling(make: Factory) -> None:
    from strandbeest_common.ops import apply_op, make_op

    from .config import sim_config
    from .runner import run

    d = _example_design()
    scaled = apply_op(d, make_op("scale", {"factor": 2.0, "keep_physical": True})).design  # every length x2, unit_m / 2
    sc_a, sc_b = sim_config(_scenario(d)), sim_config(_scenario(scaled))
    # the servo gains of scenario_from_design scale with unit_m (a proxy for walker size), which is not what is under test here:
    # give both the same physical drive so only the length unit differs
    sc_b.drive.kp, sc_b.drive.kv = sc_a.drive.kp, sc_a.drive.kv
    assert sc_a.walker.unit != sc_b.walker.unit
    a, b = run(sc_a, backend=make()), run(sc_b, backend=make())
    span = float(np.ptp(a.x))
    assert float(np.max(np.abs(a.x - b.x))) < 1e-3 * span, "the same physical walker in other length units walked differently"
    assert b.metrics["stride_per_rev"] == pytest_approx(a.metrics["stride_per_rev"], 1e-3)
    assert b.metrics["mean_torque"] == pytest_approx(a.metrics["mean_torque"], 0.02), "the torque changed with the length unit"


def pytest_approx(value: float, rel: float):
    class _A:
        def __eq__(self, other):  # noqa: D105
            return abs(other - value) <= rel * abs(value)

        def __repr__(self):
            return f"{value} ± {rel:.0%}"

    return _A()


CHECKS: dict[str, Callable[[Factory], None]] = {
    "energy_conservation": check_energy_conservation,
    "pendulum_period": check_pendulum_period,
    "incline_acceleration": check_incline_acceleration,
    "gravity_direction": check_gravity_direction,
    "snapshot_restore": check_snapshot_restore,
    "determinism": check_determinism,
    "mirror_symmetry": check_mirror_symmetry,
    "unit_scaling": check_unit_scaling,
}


def run_contract(make: Factory) -> dict[str, str | None]:
    """Run every check; the result maps each check name to None (passed) or the failure message."""
    out: dict[str, str | None] = {}
    for name, fn in CHECKS.items():
        try:
            fn(make)
            out[name] = None
        except Exception as e:  # noqa: BLE001  a crash is a failure of the contract too
            out[name] = f"{type(e).__name__}: {e}"
    return out
