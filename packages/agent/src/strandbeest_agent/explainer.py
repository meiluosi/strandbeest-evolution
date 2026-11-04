"""Automated run explainer and invariant-audited diagnostic reporter (A-05).

Synthesizes simulation events, energy balance anomalies, provenance metadata,
and invariant audit evidence into structured diagnostic reports.
Includes strict fallback and downgrade interception when physical evidence is unverified.
"""

from __future__ import annotations

from typing import Any, Mapping

from strandbeest_sim.skeptic import LOOP_OPEN_M, PENETRATION_M

CRITICAL_FAULT_KINDS = {
    "stall",
    "stalled",
    "crank_stalled",
    "motor_saturation",
    "motor_torque_saturation",
    "torque_limit",
    "loop_open",
    "loop_broken",
    "loop_violation",
    "kinematic_loop_rupture",
    "extreme_penetration",
    "deep_sinkage",
    "excessive_penetration",
    "sudden_deceleration",
    "deceleration",
    "jam",
    "toggle_jam",
    "toggle_position_jam",
    "tipping",
    "gait_desync",
    "gait_desynchronization",
    "singularity",
    "failure",
}


def _find_critical_fault_time(
    events: list[dict[str, Any]],
    invariants: Mapping[str, Any],
    stalled: bool,
) -> float | None:
    """Identify the critical event time t_fault (e.g. first stall, loop broken, extreme penetration, or sudden deceleration)."""
    # 1. Search for first explicit fault event
    for ev in events:
        kind = str(ev.get("kind", "")).lower()
        sev = str(ev.get("severity", "")).lower()
        if kind in CRITICAL_FAULT_KINDS or sev in ("error", "critical") or ev.get("is_fault"):
            return float(ev.get("t", 0.0))
        detail = ev.get("detail", {})
        if isinstance(detail, dict) and any(
            k in detail for k in ("opening_m", "limit_nm", "excessive_penetration", "toggle_jam", "singularity")
        ):
            return float(ev.get("t", 0.0))

    # 2. Invariant breaches without explicit fault event tag
    if invariants.get("loop_broken") or invariants.get("excessive_penetration"):
        for ev in events:
            if "loop" in ev.get("kind", "").lower() or "penetr" in ev.get("kind", "").lower():
                return float(ev.get("t", 0.0))
        if events:
            return float(events[-1].get("t", 0.0))

    # 3. Stalled without explicit event
    if stalled and events:
        return float(events[-1].get("t", 0.0))

    return None


def _format_event(ev: dict[str, Any]) -> str:
    t_val = float(ev.get("t", 0.0))
    kind = ev.get("kind", "unknown")
    detail = ev.get("detail", {})
    leg = ev.get("leg")
    leg_str = f" leg={leg}" if leg is not None else ""
    detail_str = f" ({detail})" if detail else ""
    return f"[{t_val:.3f}s] {kind}{leg_str}{detail_str}"


def extract_centered_timeline(
    events: list[dict[str, Any]],
    t_fault: float | None = None,
    window_s: float = 0.5,
) -> list[str]:
    """Extract events in a centered window [t_fault - 0.5s, t_fault + 0.5s], plus summary of initial launch and final state."""
    if not events:
        return []

    sorted_events = sorted(events, key=lambda e: float(e.get("t", 0.0)))
    if len(sorted_events) <= 10 or t_fault is None:
        if len(sorted_events) <= 10:
            return [_format_event(e) for e in sorted_events]
        first_events = [_format_event(e) for e in sorted_events[:4]]
        omitted = len(sorted_events) - 8
        last_events = [_format_event(e) for e in sorted_events[-4:]]
        return first_events + [f"... ({omitted} events omitted during steady cycle) ..."] + last_events

    w_start = t_fault - window_s
    w_end = t_fault + window_s

    before = [e for e in sorted_events if float(e.get("t", 0.0)) < w_start]
    inside = [e for e in sorted_events if w_start <= float(e.get("t", 0.0)) <= w_end]
    after = [e for e in sorted_events if float(e.get("t", 0.0)) > w_end]

    timeline_lines: list[str] = []

    # 1. Summary of initial launch
    if before:
        launch_ev = before[0]
        timeline_lines.append(f"[Launch] {_format_event(launch_ev)}")
        omitted_before = len(before) - 1
        if omitted_before > 0:
            timeline_lines.append(f"... ({omitted_before} events omitted prior to fault window) ...")

    # 2. Centered failure window
    if inside:
        for e in inside:
            timeline_lines.append(_format_event(e))
    else:
        closest = min(sorted_events, key=lambda e: abs(float(e.get("t", 0.0)) - t_fault))
        timeline_lines.append(_format_event(closest))

    # 3. Summary of final state
    if after:
        omitted_after = len(after) - 1
        if omitted_after > 0:
            timeline_lines.append(f"... ({omitted_after} events omitted following fault window) ...")
        final_ev = after[-1]
        timeline_lines.append(f"[Final] {_format_event(final_ev)}")

    return timeline_lines


def build_explanation_context(run_doc: Mapping[str, Any]) -> dict[str, Any]:
    """Assemble run telemetry, events, invariants, and evidence into a structured diagnostic context."""
    events = list(run_doc.get("events", []))
    diagnosis = [dict(d) for d in run_doc.get("diagnosis", [])]
    metrics = run_doc.get("metrics", {})
    provenance = run_doc.get("provenance", {})
    evidence = run_doc.get("evidence", {})
    scenario = run_doc.get("scenario", {})
    stalled = run_doc.get("stalled", False)

    # Invariant audits
    max_loop_viol = metrics.get("max_loop_violation", 0.0)
    max_pen = metrics.get("max_penetration", 0.0)
    loop_broken = max_loop_viol is not None and max_loop_viol > LOOP_OPEN_M
    stiffness_pen = max_pen is not None and max_pen > PENETRATION_M
    audit = run_doc.get("audit", {})
    audit_status = audit.get("status", "not_recorded") if audit.get("version") == 2 else "not_recorded"

    # Active evidence downgrade synthesis for skeptical AI reporting
    downgraded = bool(evidence.get("downgraded", False))
    downgrade_reasons = list(evidence.get("downgrade_reasons", []))
    if loop_broken:
        downgraded = True
        reason = f"kinematic loop violated: max residual {max_loop_viol:.4f} m > 0.005 m"
        if reason not in downgrade_reasons:
            downgrade_reasons.append(reason)
    if stiffness_pen:
        downgraded = True
        reason = f"excessive terrain penetration: max penetration {max_pen:.4f} m > {PENETRATION_M:g} m"
        if reason not in downgrade_reasons:
            downgrade_reasons.append(reason)

    # Deeper diagnostic codes:
    # 1. Check for toggle position singularity / mechanical advantage drop (TOGGLE_POSITION_JAM)
    has_toggle_code = any(str(d.get("code", "")).upper() == "TOGGLE_POSITION_JAM" for d in diagnosis)
    toggle_ev = any(
        ev.get("kind") in ("toggle_jam", "toggle_position_jam", "singularity", "mechanical_advantage_drop")
        for ev in events
    )
    min_mech_adv = metrics.get("min_mechanical_advantage")
    toggle_metric = (
        bool(metrics.get("toggle_jam"))
        or (min_mech_adv is not None and min_mech_adv < 0.05)
        or float(metrics.get("singularity_proximity", 0.0)) > 0.9
    )
    if (toggle_ev or toggle_metric) and not has_toggle_code:
        diagnosis.append({
            "code": "TOGGLE_POSITION_JAM",
            "severity": "error",
            "message": "Linkage approached toggle position singularity with severe mechanical advantage drop, causing kinematic locking.",
            "evidence": {
                "min_mechanical_advantage": min_mech_adv if min_mech_adv is not None else 0.0,
                "singularity_proximity": metrics.get("singularity_proximity", 1.0),
            },
        })

    # 2. Check for gait desynchronization (GAIT_DESYNC_TIPPING)
    has_desync_code = any(str(d.get("code", "")).upper() == "GAIT_DESYNC_TIPPING" for d in diagnosis)
    desync_ev = any(
        ev.get("kind") in ("gait_desync", "gait_desynchronization", "tipping", "body_tilt_exceeded", "loss_of_support")
        for ev in events
    )
    max_tilt = metrics.get("max_tilt_rad")
    margin = metrics.get("support_polygon_margin")
    desync_metric = (
        bool(metrics.get("gait_desync"))
        or (max_tilt is not None and max_tilt > 0.35)
        or (margin is not None and margin < -0.01)
    )
    if (desync_ev or desync_metric) and not has_desync_code:
        diagnosis.append({
            "code": "GAIT_DESYNC_TIPPING",
            "severity": "error",
            "message": "Leg phasing desynchronization resulted in loss of stance support polygon, causing vehicle pitch/roll instability and tipping.",
            "evidence": {
                "max_tilt_rad": max_tilt if max_tilt is not None else 0.0,
                "support_polygon_margin": margin if margin is not None else -0.05,
            },
        })

    # Energy accounting
    e_in = metrics.get("energy_in_per_rev")
    steady = metrics.get("steady_window", 0.0)

    # Chronological key events
    sorted_events = sorted(events, key=lambda e: float(e.get("t", 0.0)))
    timeline = [_format_event(ev) for ev in sorted_events]

    invariants_dict = {
        "max_loop_violation_m": max_loop_viol,
        "loop_broken": loop_broken,
        "max_penetration_m": max_pen,
        "excessive_penetration": stiffness_pen,
    }

    t_fault = _find_critical_fault_time(sorted_events, invariants_dict, stalled)
    windowed_timeline = extract_centered_timeline(sorted_events, t_fault=t_fault)

    return {
        "run_id": run_doc.get("id", "unknown"),
        "design_id": run_doc.get("design_id", "unknown"),
        "design_name": run_doc.get("design_name", "unknown"),
        "scenario_name": scenario.get("name", "unnamed"),
        "engine": provenance.get("engine", "mujoco"),
        "stalled": stalled,
        "fault_time": t_fault,
        "evidence_level": evidence.get("level", "E0"),
        "downgraded": downgraded,
        "downgrade_reasons": downgrade_reasons,
        "invariants": invariants_dict,
        "audit_status": audit_status,
        "diagnosis": diagnosis,
        "timeline": timeline,
        "windowed_timeline": windowed_timeline,
        "metrics": {
            "stride_per_rev": metrics.get("stride_per_rev"),
            "mean_torque": metrics.get("mean_torque"),
            "peak_torque": metrics.get("peak_torque"),
            "energy_in_per_rev": e_in,
            "steady_window": steady,
        },
    }


def explain_run(run_doc: Mapping[str, Any]) -> dict[str, Any]:
    """Generate a structured diagnostic report based on invariant audit and event telemetry."""
    ctx = build_explanation_context(run_doc)

    sections = []
    invariants = ctx["invariants"]
    diagnosis = ctx["diagnosis"]
    windowed_timeline = ctx.get("windowed_timeline") or ctx.get("timeline", [])

    # 1. Summary
    if ctx["stalled"]:
        diag_codes = [d.get("code") for d in diagnosis]
        code_summary = ", ".join(filter(None, diag_codes)) or "unspecified_stall"
        summary = f"Simulation stalled (diagnosis: {code_summary})."
    elif invariants["loop_broken"]:
        summary = "Simulation completed with kinematic loop rupture (structural failure)."
    else:
        summary = "Simulation completed normally within target revolutions."

    sections.append(f"### Summary\n{summary}")

    # 2. Invariant & Evidence Audit
    inv_lines = [
        f"- Numerical Audit v2: {ctx['audit_status']}",
        f"- Evidence Level: {ctx['evidence_level']}",
        f"- Max Loop Violation: {invariants['max_loop_violation_m']:.4f} m ({'VIOLATED' if invariants['loop_broken'] else 'OK'})",
        f"- Max Terrain Penetration: {invariants['max_penetration_m']:.4f} m ({'VIOLATED' if invariants['excessive_penetration'] else 'OK'})",
    ]
    if ctx["downgraded"]:
        inv_lines.append(f"- Evidence Downgrade: YES (reasons: {', '.join(ctx['downgrade_reasons'])})")
    sections.append("### Invariant & Evidence Audit\n" + "\n".join(inv_lines))

    # 3. Key Timeline Events (Centered Failure Window)
    if windowed_timeline:
        sections.append("### Key Event Timeline\n" + "\n".join(windowed_timeline))
    else:
        sections.append("### Key Event Timeline\n(No discrete events logged)")

    # 4. Diagnostic Explanations and Root Causes
    if diagnosis:
        diag_lines = []
        for d in diagnosis:
            code = d.get("code", "unknown")
            sev = d.get("severity", "info").upper()
            msg = d.get("message", "")
            ev = d.get("evidence", {})
            diag_lines.append(f"- **[{sev}] {code}**: {msg} (Evidence: {ev})")
        sections.append("### Root Cause Analysis\n" + "\n".join(diag_lines))

    report_markdown = "\n\n".join(sections)

    return {
        "summary": summary,
        "evidence_level": ctx["evidence_level"],
        "downgraded": ctx["downgraded"],
        "report_markdown": report_markdown,
        "context": ctx,
    }
