"""A-03: the simulator skeptic passes a healthy simulator and reports the two historical bugs when they are put back."""

import json

import pytest
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import builder, metrics_builtin, run, scenario_from_design
from strandbeest_sim.runner import make_sim
from strandbeest_sim.skeptic import audit, check_no_foot_foot_contacts, check_window_invariance, fuzz

DESIGN_DOC = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())
DESIGN = Design(DESIGN_DOC)


def go(revolutions: float, **ov):
    return run(scenario_from_design(DESIGN, {"run": {"revolutions": revolutions, "settle": 0.4, "frame_rate": 0}, **ov}))


def metrics_at(revolutions: float):
    return go(revolutions).metrics


def test_a_healthy_simulator_passes_every_check():
    sim = make_sim(scenario_from_design(DESIGN, {"run": {"settle": 0.3}}))
    assert check_no_foot_foot_contacts(sim) == []
    res = go(3.0)
    assert audit(res.scenario, res.metrics, res.series, res.stalled) == []
    assert check_window_invariance(metrics_at) == []


@pytest.mark.slow
def test_the_overlapping_foot_spheres_bug_is_caught_when_put_back(monkeypatch):
    monkeypatch.setattr(builder, "LEGACY_FOOT_BUG", True)
    sim = make_sim(scenario_from_design(DESIGN, {"run": {"settle": 0.3}}))
    findings = check_no_foot_foot_contacts(sim)
    assert findings and findings[0].check == "no_foot_foot_contacts"


@pytest.mark.slow
def test_the_partial_window_bias_is_caught_when_put_back(monkeypatch):
    monkeypatch.setattr(metrics_builtin, "LEGACY_WINDOW", True)
    findings = check_window_invariance(metrics_at)
    assert findings and findings[0].check == "window_invariance"
    assert max(f.evidence["relative"] for f in findings) > 0.04


@pytest.mark.slow
def test_audit_flags_soft_contact_and_a_blocked_walker():
    soft = go(2.1, terrain={"kind": "soft", "params": {"stiffness": 4000.0, "damping": 120.0}})
    assert "penetration" in {f.check for f in audit(soft.scenario, soft.metrics, soft.series, soft.stalled)}
    step = go(2.1, terrain={"kind": "step", "params": {"distance": 0.15, "height": 0.012}})
    assert "loop_closure" in {f.check for f in audit(step.scenario, step.metrics, step.series, step.stalled)}


@pytest.mark.slow
def test_fuzzing_reports_broken_invariants_and_explains_the_big_energy_residuals():
    """The fuzzer found that about half of random, guard-valid walkers (four lengths changed by up to 8 %, 4/6/8 legs) open a
    loop by more than 5 mm (docs/EXPERIMENTS.md section 15). This test does not pretend otherwise: it checks that what the
    skeptic reports is of the known kinds and that a large energy residual always comes with an open loop (the model has come
    apart, so the account is meaningless), never alone."""
    bad = fuzz(5, seed=1)
    for design, findings in bad:
        kinds = {f.check for f in findings}
        assert kinds <= {"energy_closure", "loop_closure", "penetration", "stride_vs_kinematics", "support"}, kinds
        big = [f for f in findings if f.check == "energy_closure" and abs(f.evidence["residual_share"]) > 0.05]
        if big:
            assert "loop_closure" in kinds, (design, [str(f) for f in findings])
