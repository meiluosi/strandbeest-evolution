"""Independent analytic checks for the experimental signed stride reference.

The production audit is deliberately unchanged pending physical validation.
"""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "signed_stride_study", Path(__file__).parents[1] / "scripts/hardening_g1_stride_oracle.py"
)
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)


@pytest.mark.parametrize("foot_velocity", [-2.0, 2.0, 0.0, 1e-10])
def test_compatible_support_velocity_is_the_negative_foot_velocity(foot_velocity):
    result = reference.fit_support([foot_velocity, foot_velocity])
    assert result["velocity"] == -foot_velocity
    assert result["rms_slip"] == 0.0
    assert result["spread"] == 0.0


def test_opposing_supports_do_not_become_a_compatible_zero_velocity():
    result = reference.fit_support([-2., 2.])
    assert result["velocity"] == 0.
    assert result["rms_slip"] == 2.
    assert result["spread"] == 4.


def test_no_support_is_unidentified_not_zero_motion():
    assert reference.fit_support([])["velocity"] is None
    assert reference.lowest_foot_stride(lambda a: (0., 0.), phases=[], direction=1, unit=1., brackets=72)["stride"] is None


def test_elliptical_feet_match_the_closed_form_cycle_integral_forward_reverse_and_near_zero():
    rows = reference.analytic_checks()
    assert len(rows) == 6
    # The smallest nonzero case stays signed and nonzero; no denominator floor.
    assert rows[-1]["endpoint"]["stride"] < 0
    assert abs(rows[-1]["endpoint"]["stride"]) < 1e-9
