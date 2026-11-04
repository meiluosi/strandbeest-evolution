"""Signed external work is still subject to the same energy balance."""
from types import SimpleNamespace

import numpy as np
import pytest

from strandbeest_sim.metrics_builtin import energy


@pytest.mark.parametrize("work", [-2.0, 2.0])
@pytest.mark.parametrize("residual_share", [0.0, 0.025, -0.025])
def test_energy_balance_includes_absorbed_work_and_detects_both_residual_signs(work, residual_share):
    psi = np.linspace(0, 6 * np.pi, 61)
    ramp = lambda per_rev: psi / (2 * np.pi) * per_rev
    # Independently prescribe W = D_contact + D_loop + delta(E) + residual.
    # The negative-work case releases 4 J/rev of stored energy while 2 J/rev
    # leaves through the drive and another 2 J/rev is dissipated.
    result = SimpleNamespace(psi=psi, series={
        "e_in": ramp(work), "e_contact": ramp(1.5), "e_loops": ramp(.5),
        "e_friction": ramp(0), "kinetic": ramp(0) + .1,
        "potential": ramp(work - 2 - work*residual_share) + 10,
    })
    metrics = energy(result)
    assert metrics["energy_in_per_rev"] == pytest.approx(work)
    assert metrics["energy_contact_share"] == pytest.approx(1.5/work)
    assert metrics["energy_loops_share"] == pytest.approx(.5/work)
    assert metrics["energy_residual_share"] == pytest.approx(residual_share, abs=1e-14)
    assert (abs(metrics["energy_residual_share"]) > .02) == (abs(residual_share) > .02)


@pytest.mark.parametrize("work", [0., 1e-14, -1e-14])
def test_zero_net_work_does_not_invent_a_relative_energy_balance(work):
    psi = np.linspace(0, 6*np.pi, 61)
    ramp = lambda per_rev: psi / (2*np.pi) * per_rev
    result = SimpleNamespace(psi=psi, series={
        "e_in": ramp(work), "e_contact": ramp(1), "e_loops": ramp(0),
        "e_friction": ramp(0), "kinetic": ramp(0), "potential": ramp(-1),
    })
    assert set(energy(result)) == {"energy_window_revs"}


@pytest.mark.parametrize("work", [-2., 2.])
@pytest.mark.parametrize("residual", [-.025, .025])
def test_numerical_diagnostic_cannot_cancel_a_failing_energy_audit(work, residual):
    from strandbeest_sim.audit import audit_report
    from strandbeest_sim.config import sim_config
    from strandbeest_sim.contract import _example_design, _scenario
    from strandbeest_sim.skeptic import audit_legacy

    psi = np.linspace(0, 6*np.pi, 61)
    ramp = lambda per_rev: psi / (2*np.pi) * per_rev
    series = {
        "e_in": ramp(work), "e_contact": ramp(.5), "e_loops": ramp(0),
        "e_friction": ramp(0), "kinetic": ramp(0) + .1,
        "potential": ramp(work-.5-work*residual) + 10,
    }
    result = SimpleNamespace(psi=psi, series=series)
    original = energy(result)
    series.update({"e_contact_normal": ramp(-.2), "e_contact_tangent": ramp(.7),
                   "e_numerical": ramp(-work*residual)})
    account = energy(result)
    # Diagnostic-only fields cannot alter any ordinary account term.
    assert {k: account[k] for k in original} == original
    assert account["energy_numerical_share"] == pytest.approx(-residual)
    assert account["energy_contact_normal_share"] == pytest.approx(-.2/work)
    assert account["energy_contact_tangent_share"] == pytest.approx(.7/work)
    metrics = {**account, "steady_window": 1, "stride_per_rev": .1,
               "max_loop_violation": 0, "max_penetration": 0}
    sc = sim_config(_scenario(_example_design()))
    assert "energy_closure" in [f.check for f in audit_legacy(sc, metrics)]
    current = audit_report(sc, metrics, backend_name="k2")
    assert current["status"] == "failed"
    assert "energy_closure" in [f["check"] for f in current["findings"]]
