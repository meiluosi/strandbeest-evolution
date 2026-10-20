from strandbeest_common import (
    audit_run_evidence,
    default_evidence,
    downgrade_evidence,
    evaluate_evidence,
    validate,
)


def test_default_evidence_is_e0():
    ev = default_evidence({"stride_per_rev": 0.25, "mean_speed": 0.08})
    assert ev["level"] == "E0"
    assert "single-model-simulation" in ev["basis"]
    assert ev["claims"]["stride_per_rev"]["level"] == "E0"


def test_cross_checks_and_literature_raise_evidence_levels():
    metrics = {"stride_per_rev": 0.25, "foot_path": None}
    ev = evaluate_evidence(
        metrics,
        cross_checks={"stride_per_rev": {"verified": True, "basis": ["k2-mujoco-crosscheck"]}},
        literature_checks={"foot_path": {"verified": True, "basis": ["digitized-amm2014-trajectory"]}},
    )
    assert ev["claims"]["stride_per_rev"]["level"] == "E1"
    assert "k2-mujoco-crosscheck" in ev["claims"]["stride_per_rev"]["basis"]
    assert ev["claims"]["foot_path"]["level"] == "E2"
    assert ev["level"] == "E2"


def test_downgrade_evidence_when_invariants_fail():
    ev = evaluate_evidence(
        {"stride_per_rev": 0.25},
        cross_checks={"stride_per_rev": {"verified": True, "basis": ["k2-mujoco-crosscheck"]}},
    )
    assert ev["claims"]["stride_per_rev"]["level"] == "E1"

    # Invariant breach: loop opened 8 mm
    run_doc = {
        "metrics": {"max_loop_violation": 0.008, "stride_per_rev": 0.25},
        "evidence": ev,
        "stalled": False,
    }
    audited = audit_run_evidence(run_doc)
    assert audited["level"] == "E0"
    assert audited["claims"]["stride_per_rev"]["level"] == "E0"
    assert audited["claims"]["stride_per_rev"]["downgraded"] is True
    assert "loop_opened_8.0mm" in audited["claims"]["stride_per_rev"]["downgrade_reason"]


def test_downgrade_evidence_on_known_bug():
    ev = evaluate_evidence(
        {"stride_per_rev": 0.25},
        cross_checks={"stride_per_rev": {"verified": True, "basis": ["k2-mujoco-crosscheck"]}},
    )
    audited = audit_run_evidence({"metrics": {}, "evidence": ev}, known_bugs=["regression_friction_sign"])
    assert audited["level"] == "E0"
    assert "bug:regression_friction_sign" in audited["downgrade_reason"]


def test_run_schema_validates_evidence_field():
    sample_run = {
        "schema_version": 2,
        "id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "design_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "scenario": {},
        "metrics": {"stride_per_rev": 0.25},
        "provenance": {"code_version": "test"},
        "evidence": default_evidence({"stride_per_rev": 0.25}),
    }
    validate("run", sample_run)
