import math

import numpy as np
import pytest

from strandbeest_calib import curves, distance


def synth(offset=0.0, scale=1.0, revs=3):
    psi = np.linspace(0, revs * 2 * math.pi, 600)
    return np.linspace(0, 10, 600), psi, scale * (1.0 + 0.5 * np.sin(psi)) + offset, 0.05 * psi


def test_identical_curves_have_zero_distance():
    a = curves(*synth(), skip_rev=0.5)
    assert distance(a, a) == pytest.approx(0.0)


def test_distance_grows_with_mismatch():
    a = curves(*synth(), skip_rev=0.5)
    near = curves(*synth(offset=0.05), skip_rev=0.5)
    far = curves(*synth(offset=0.5), skip_rev=0.5)
    assert 0 < distance(a, near) < distance(a, far)


def test_stride_is_distance_per_revolution():
    c = curves(*synth(), skip_rev=0.5)
    assert c.stride == pytest.approx(0.05 * 2 * math.pi, rel=1e-3)
