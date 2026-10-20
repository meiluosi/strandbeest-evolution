"""Evidence level system (V-07, docs/VALIDATION.md).

Every result, metric or simulation run carries an evidence level:
- E0: Single model simulation (default for all new/unvalidated runs)
- E1: Dual independent solvers agree within agreed tolerance (e.g. K2 vs MuJoCo)
- E2: Verified against public data or published literature (e.g. V-01 digitized trajectory)
- E3: Verified by traceable physical measurements (physical test rig)

Downgrade rules:
- Any broken invariant (loop opening > 5 mm, energy residual > 2 %, stall) or known bug
  forces a downgrade to E0 with an explicit reason recorded in the document.
"""

from __future__ import annotations

from typing import Any, Literal

EvidenceLevel = Literal["E0", "E1", "E2", "E3"]
EVIDENCE_LEVELS: tuple[EvidenceLevel, ...] = ("E0", "E1", "E2", "E3")

LEVEL_ORDER: dict[EvidenceLevel, int] = {"E0": 0, "E1": 1, "E2": 2, "E3": 3}


def default_claim(level: EvidenceLevel = "E0", basis: list[str] | None = None) -> dict[str, Any]:
    return {
        "level": level,
        "basis": basis if basis is not None else ["single-model-simulation"],
    }


def default_evidence(metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Default E0 evidence structure for a fresh simulation run."""
    claims = {
        "stride_per_rev": default_claim("E0", ["single-model-simulation"]),
        "mean_speed": default_claim("E0", ["single-model-simulation"]),
        "mean_torque": default_claim("E0", ["single-model-simulation"]),
        "foot_path": default_claim("E0", ["single-kinematic-solver"]),
    }
    if metrics:
        for k in metrics:
            if k not in claims:
                claims[k] = default_claim("E0", ["single-model-simulation"])
    return {
        "level": "E0",
        "basis": ["single-model-simulation"],
        "claims": claims,
    }


def evaluate_evidence(
    metrics: dict[str, Any],
    cross_checks: dict[str, Any] | None = None,
    literature_checks: dict[str, Any] | None = None,
    measurement_checks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an evidence document incorporating independent cross-checks or literature comparisons."""
    doc = default_evidence(metrics)
    claims = doc["claims"]

    # 1. Measurement checks (E3)
    if measurement_checks:
        for key, info in measurement_checks.items():
            if info.get("verified", False):
                basis = info.get("basis", ["physical-rig-measurement"])
                claims[key] = {"level": "E3", "basis": basis}

    # 2. Literature checks (E2)
    if literature_checks:
        for key, info in literature_checks.items():
            if info.get("verified", False):
                basis = info.get("basis", ["published-literature"])
                claims[key] = {"level": "E2", "basis": basis}

    # 3. Cross-solver verification (E1)
    if cross_checks:
        for key, info in cross_checks.items():
            if info.get("verified", False):
                # Don't overwrite higher E2/E3 level
                current = claims.get(key, {}).get("level", "E0")
                if LEVEL_ORDER.get(current, 0) < LEVEL_ORDER["E1"]:
                    basis = info.get("basis", ["dual-solver-cross-check"])
                    claims[key] = {"level": "E1", "basis": basis}

    # Derive overall level: the highest level among verified core claims
    levels = [c.get("level", "E0") for c in claims.values()]
    best_level = max(levels, key=lambda l: LEVEL_ORDER.get(l, 0)) if levels else "E0"
    doc["level"] = best_level
    doc["basis"] = list(dict.fromkeys(b for c in claims.values() for b in c.get("basis", [])))
    return doc


def downgrade_evidence(
    evidence: dict[str, Any],
    claim_key: str | None = None,
    reason: str = "invariant_violation",
) -> dict[str, Any]:
    """Downgrade a claim or the entire run to E0 following an invariant breach or known bug."""
    out = dict(evidence)
    claims = {k: dict(v) for k, v in out.get("claims", {}).items()}

    if claim_key is not None:
        if claim_key in claims:
            claims[claim_key]["level"] = "E0"
            claims[claim_key]["downgraded"] = True
            claims[claim_key]["downgrade_reason"] = reason
    else:
        for k in claims:
            claims[k]["level"] = "E0"
            claims[k]["downgraded"] = True
            claims[k]["downgrade_reason"] = reason
        out["level"] = "E0"
        out["downgraded"] = True
        out["downgrade_reason"] = reason

    # Update top-level level if all claims are E0
    levels = [c.get("level", "E0") for c in claims.values()]
    out["level"] = max(levels, key=lambda l: LEVEL_ORDER.get(l, 0)) if levels else "E0"
    out["claims"] = claims
    return out


def audit_run_evidence(run_doc: dict[str, Any], known_bugs: list[str] | None = None) -> dict[str, Any]:
    """Ensure run evidence is downgraded if simulator invariants or known bugs fail."""
    ev = dict(run_doc.get("evidence") or default_evidence(run_doc.get("metrics")))
    metrics = run_doc.get("metrics", {})

    reasons: list[str] = []
    # Check loop violation (> 5 mm)
    if metrics.get("max_loop_violation", 0.0) > 0.005:
        reasons.append(f"loop_opened_{1000 * metrics['max_loop_violation']:.1f}mm")

    # Check energy residual (> 2 %) on steady runs (steady_window >= 1.0)
    if metrics.get("steady_window", 0.0) >= 1.0:
        res = metrics.get("energy_residual_share")
        if res is not None and abs(res) > 0.02:
            reasons.append(f"energy_residual_{res * 100:.1f}pct")

    # Check stalled
    if run_doc.get("stalled"):
        reasons.append("stalled_run")

    # Check known bugs
    if known_bugs:
        for bug in known_bugs:
            reasons.append(f"bug:{bug}")

    if reasons:
        ev = downgrade_evidence(ev, None, "; ".join(reasons))

    return ev
