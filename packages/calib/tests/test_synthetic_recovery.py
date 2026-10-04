"""Can the calibration machinery recover known parameters from synthetic data? (minutes; run with -m slow)"""

import pytest

from strandbeest_calib import CONTACT_SOLREF, FRICTION, calibrate, make_synthetic_measurement
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir

pytestmark = pytest.mark.slow


def test_recovers_contact_stiffness_from_synthetic_data():
    d = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
    truth = {"contact_solref": 0.01}
    meas = make_synthetic_measurement(d, truth, [CONTACT_SOLREF], noise=0.02, seed=1)
    profile = calibrate(d, meas, [CONTACT_SOLREF], max_evals=25)
    got = profile["parameters"]["contact_solref"]
    assert got == pytest.approx(truth["contact_solref"], rel=0.35)
