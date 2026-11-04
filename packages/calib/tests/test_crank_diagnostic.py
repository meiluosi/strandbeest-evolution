"""Independent scalar-rotor oracles and prevention of holdout leakage."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

SPEC = importlib.util.spec_from_file_location('crank_diagnostic', Path(__file__).resolve().parents[1] / 'scripts/validate_crank_dynamics.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SPEC_COULOMB = importlib.util.spec_from_file_location('crank_coulomb_diagnostic', Path(__file__).resolve().parents[1] / 'scripts/diagnose_crank_medium_error.py')
COULOMB_MOD = importlib.util.module_from_spec(SPEC_COULOMB)
SPEC_COULOMB.loader.exec_module(COULOMB_MOD)


@pytest.mark.parametrize('damping', [0.0, 1e-14, .01])
def test_exact_rotor_static_equilibrium_is_preserved(damping):
    omega0, bias = 3.0, .002
    torque = np.full(1000, damping*omega0+bias)
    theta, omega = MODULE.linear_rollout(torque, .001, .003716, damping, bias, -.2, omega0)
    np.testing.assert_allclose(omega, omega0, atol=1e-12)
    np.testing.assert_allclose(theta, -.2 + omega0*np.arange(1001)*.001, atol=1e-12)


def test_constant_torque_preserves_work_kinetic_energy_identity():
    inertia, torque, dt = .003716, .03, .001
    theta, omega = MODULE.linear_rollout(np.full(1000, torque), dt, inertia, 0, 0, .4, -2)
    np.testing.assert_allclose(torque*(theta-.4), .5*inertia*(omega**2-4), atol=1e-12)
    assert omega[-1] == pytest.approx(-2+torque/inertia, abs=1e-12)


def test_unforced_viscous_decay_agrees_with_time_constant():
    inertia, damping = .003716, .01
    theta, omega = MODULE.linear_rollout(np.zeros(1000), .001, inertia, damping, 0, 0, 3)
    assert omega[-1] == pytest.approx(3*np.exp(-damping/inertia), rel=1e-12)
    assert theta[-1] == pytest.approx(3*inertia/damping*(1-np.exp(-damping/inertia)), rel=1e-12)
    assert np.all(np.diff(omega) < 0)


def test_native_rotor_converges_toward_independent_exact_response():
    torque = .02*np.sin(np.arange(500)*.03)
    exact = MODULE.linear_rollout(torque, .005, .003716, .004, .001, .2, -1)
    coarse = MODULE.native_rollout(torque, .005, .003716, .004, .001, .2, -1, .0001)
    fine = MODULE.native_rollout(torque, .005, .003716, .004, .001, .2, -1, .00005)
    for i in range(2):
        e0 = np.max(np.abs(coarse[i]-exact[i]))
        e1 = np.max(np.abs(fine[i]-exact[i]))
        assert e1 < .51*e0


def test_identification_rejects_any_holdout_row():
    with pytest.raises(ValueError, match='holdout'):
        MODULE.fit([{'split': 'holdout', 'X': np.eye(2), 'Y': np.ones(2)}])


@pytest.mark.parametrize('field,value', [('split', 'train'), ('condition', 'cw_fast'), ('bytes', 101)])
def test_acquisition_manifest_cannot_relabel_a_locked_holdout(field, value):
    selected = [{'name': 'fixed.ASC', 'split': 'holdout', 'condition': 'cw_medium', 'bytes': 100}]
    record = {**selected[0], field: value, 'local_path': '/not/read/by/this/check'}
    with pytest.raises(ValueError, match='locked plan'):
        MODULE.validate_records(selected, [record])


def test_coulomb_rollout_reduces_to_linear_rollout_when_coulomb_is_zero():
    torque = 0.03 * np.cos(np.arange(400) * 0.02)
    th_lin, om_lin = MODULE.linear_rollout(torque, 0.005, 0.003716, 0.003, -0.001, 0.1, -2.5)
    th_coul, om_coul = COULOMB_MOD.coulomb_rollout(torque, 0.005, 0.003716, 0.003, 0.0, -0.001, 0.1, -2.5)
    np.testing.assert_allclose(th_coul, th_lin, atol=1e-12)
    np.testing.assert_allclose(om_coul, om_lin, atol=1e-12)


def test_coulomb_stiction_holds_zero_velocity_below_breakaway_and_arrests_at_zero_crossing():
    # Sub-breakaway torque from rest stays at rest
    th, om = COULOMB_MOD.coulomb_rollout(np.full(100, 0.012), 0.001, 0.003716, 0.002, 0.015, 0.0, 0.5, 0.0)
    np.testing.assert_allclose(om, 0.0, atol=1e-15)
    np.testing.assert_allclose(th, 0.5, atol=1e-15)

    # Unforced deceleration under pure Coulomb friction comes to exact rest in finite time t_stop = I * |omega0| / tau_c
    inertia, coulomb, omega0 = 0.003716, 0.015, 1.5
    t_stop = inertia * omega0 / coulomb  # 0.3716 s
    th2, om2 = COULOMB_MOD.coulomb_rollout(np.zeros(500), 0.001, inertia, 0.0, coulomb, 0.0, 0.0, omega0)
    assert om2[-1] == 0.0
    assert th2[-1] == pytest.approx(0.5 * omega0 * t_stop, rel=1e-12)


def test_native_coulomb_rollout_agrees_with_analytic_coulomb_rollout():
    torque = np.full(300, -0.025)
    exact_th, exact_om = COULOMB_MOD.coulomb_rollout(torque, 0.005, 0.003716, 0.0026, 0.0148, -0.0019, 0.0, -2.8)
    native_th, native_om = COULOMB_MOD.native_coulomb_rollout(
        torque, 0.005, 0.003716, 0.0026, 0.0148, -0.0019, 0.0, -2.8, 0.0001
    )
    np.testing.assert_allclose(native_om, exact_om, atol=5e-4)
    np.testing.assert_allclose(native_th, exact_th, atol=1e-3)


def test_coulomb_identification_rejects_holdout_row():
    with pytest.raises(ValueError, match="holdout"):
        COULOMB_MOD.fit_coulomb([{"split": "holdout", "X3": np.eye(3), "Y3": np.ones(3)}])
