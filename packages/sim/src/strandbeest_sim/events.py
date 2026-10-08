"""Events and automatic diagnosis from a finished run (G-04, E4-06 in its first form).

Everything here works on the recorded series of a `Result` and the flat configuration, so it is independent of the physics
backend. Events are facts with a time (a foot touches down, a foot slips, the motor reaches its torque limit, the loops
open, the crank starts, a gust peaks). Diagnosis is rules that look for evidence among the events and the invariants:
it names a cause and lists the numbers that support it. Wording by an AI model can come later; the evidence cannot be invented.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .config import SimConfig

SLIP_SPEED = 0.02  # m/s of tangential foot speed that counts as slipping while loaded
SLIP_MIN_SAMPLES = 3
TORQUE_LIMIT_FRACTION = 0.98
TORQUE_LIMIT_MIN_S = 0.006
WEAK_SAIL_RATIO = 0.15  # mean crank speed below this share of the sail's free-running speed: the load takes nearly all of the sail torque
LOOP_OPEN_M = 0.005  # a loop closure open by more than 5 mm: the model has come apart


def _runs(mask: np.ndarray, min_len: int = 1) -> list[tuple[int, int]]:
    """[start, end] index pairs of the True runs in a boolean array."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if j - i + 1 >= min_len:
                out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def detect_events(res: Any, sc: SimConfig | None = None) -> list[dict[str, Any]]:
    """Events of a run in time order: {t, kind, leg?, detail?}. `res` is a runner.Result."""
    sc = sc or res.scenario
    t = np.asarray(res.t)
    ev: list[dict[str, Any]] = []
    s = getattr(res, "series", {}) or {}
    if len(t) == 0:
        return ev

    moving = np.flatnonzero(np.asarray(res.psi) > 0.05)
    if len(moving):
        ev.append({"t": float(t[moving[0]]), "kind": "start"})
    if res.stalled:
        ev.append({"t": float(t[-1]), "kind": "stall", "detail": {"crank_rotation_rad": float(res.psi[-1])}})

    if "foot_normal" in s:
        normal = np.asarray(s["foot_normal"])
        slip = np.asarray(s["foot_slip"])
        for leg in range(normal.shape[1]):
            down = normal[:, leg] > 1e-6
            for a, b in _runs(down):
                if a > 0:
                    ev.append({"t": float(t[a]), "kind": "touchdown", "leg": leg})
                if b < len(t) - 1:
                    ev.append({"t": float(t[b]), "kind": "liftoff", "leg": leg})
            for a, b in _runs(down & (slip[:, leg] > SLIP_SPEED), SLIP_MIN_SAMPLES):
                ev.append({"t": float(t[a]), "kind": "slip", "leg": leg, "detail": {"duration_s": float(t[b] - t[a]), "peak_speed_m_s": float(slip[a : b + 1, leg].max())}})

    cap = sc.drive.max_torque
    if cap and sc.drive.kind == "motor":
        sat = np.abs(np.asarray(res.torque)) >= TORQUE_LIMIT_FRACTION * cap
        for a, b in _runs(sat):
            if t[b] - t[a] >= TORQUE_LIMIT_MIN_S:
                ev.append({"t": float(t[a]), "kind": "torque_limit", "detail": {"duration_s": float(t[b] - t[a]), "limit_nm": float(cap)}})

    if "loop_residual" in s:
        opened = np.flatnonzero(np.asarray(s["loop_residual"]) > LOOP_OPEN_M)
        if len(opened):
            ev.append({"t": float(t[opened[0]]), "kind": "loop_open", "detail": {"opening_m": float(np.asarray(s["loop_residual"])[opened[0]])}})

    if sc.wind.kind == "gusts" and sc.drive.kind == "sail":
        period = float(sc.wind.params.get("period", 6.0))
        k = 0
        while period * (k + 0.25) <= t[-1]:
            ev.append({"t": period * (k + 0.25), "kind": "gust", "detail": {"speed_m_s": float(sc.wind.speed + sc.wind.params.get("amplitude", 1.0))}})
            k += 1

    return sorted(ev, key=lambda e: (e["t"], e["kind"], e.get("leg", -1)))


def nominal_stride_m(sc: SimConfig) -> float | None:
    """Distance one crank revolution carries the body if no foot slipped or was blocked (stance travel / duty factor)."""
    from strandbeest_common import gait_metrics, load_spec

    spec = sc.linkage.spec
    if not isinstance(spec, dict):
        return None
    g = gait_metrics(load_spec(spec))
    return g.stroke_length / g.duty * sc.walker.unit if g.duty > 0 else None


def diagnose(res: Any, events: list[dict[str, Any]] | None = None, sc: SimConfig | None = None) -> list[dict[str, Any]]:
    """Why did the run end up like this? A list of {code, severity, message, evidence} (best explanation first)."""
    sc = sc or res.scenario
    events = events if events is not None else detect_events(res, sc)
    t = np.asarray(res.t)
    m = res.metrics
    out: list[dict[str, Any]] = []
    nominal = nominal_stride_m(sc)
    stride = m.get("stride_per_rev")
    efficiency = (stride / nominal) if (nominal and stride is not None and stride == stride) else None
    advanced = float(res.x[-1] - res.x[0]) if len(res.x) > 1 else 0.0
    duration = float(t[-1]) if len(t) else 0.0

    def add(code, severity, message, **evidence):
        out.append({"code": code, "severity": severity, "message": message, "evidence": evidence})

    sail = sc.drive.kind == "sail"
    if res.stalled and sail:
        d = sc.drive
        wind = sc.wind.speed
        tau0 = d.sail_gear * 0.5 * sc.environment.air_density * d.sail_drag_coeff * d.sail_area * d.sail_radius * wind * wind
        add("sail_torque_insufficient", "error",
            f"The sail did not turn the crank: at standstill it gives about {tau0 * 1000:.2f} mN·m in a {wind:g} m/s wind and {sc.environment.air_density:g} kg/m³ air, "
            "which is not enough to overcome the starting load of the walker.",
            wind_m_s=wind, air_density_kg_m3=sc.environment.air_density, sail_standstill_torque_nm=tau0,
            crank_rotation_rad=float(res.psi[-1]) if len(res.psi) else 0.0, waited_s=duration)
    if sail and not res.stalled and duration > 0:
        free = sc.wind.speed / (sc.drive.sail_gear * sc.drive.sail_radius) if sc.wind.speed > 0 else 0.0
        omega = float(res.psi[-1]) / duration
        if free > 0 and omega < WEAK_SAIL_RATIO * free:
            add("sail_weak", "warning", f"The sail barely turns the crank: {omega:.2f} rad/s on average, only {omega / free:.0%} of the {free:.2f} rad/s the sail reaches unloaded. The load takes nearly all of the sail torque.",
                mean_crank_speed_rad_s=omega, free_speed_rad_s=free, ratio=omega / free, wind_m_s=sc.wind.speed, air_density_kg_m3=sc.environment.air_density)
    kinds = {e["kind"] for e in events}
    limit_events = [e for e in events if e["kind"] == "torque_limit"]
    limit_time = sum(e["detail"]["duration_s"] for e in limit_events)
    if sc.drive.kind == "motor" and sc.drive.max_torque and (limit_time > 0.02 * max(duration, 1e-9) or len(limit_events) >= 2):
        has_obstacles = sc.terrain.kind in ("step", "bumps")
        if efficiency is not None and efficiency < 0.5 or res.stalled:
            if has_obstacles:
                add("blocked_by_terrain_torque_limit", "error",
                    f"The walker is blocked by the terrain ({sc.terrain.kind}) and the motor reaches its torque limit ({sc.drive.max_torque:g} N·m) {len(limit_events)} time(s), {limit_time / duration:.0%} of the run in total.",
                    terrain=sc.terrain.kind, torque_limit_nm=sc.drive.max_torque, time_at_limit_s=limit_time, time_at_limit_share=limit_time / max(duration, 1e-9), times_at_limit=len(limit_events), advance_efficiency=efficiency, advanced_m=advanced)
            else:
                add("torque_limit_too_low", "error",
                    f"The motor reaches its torque limit ({sc.drive.max_torque:g} N·m) {len(limit_events)} time(s), {limit_time / duration:.0%} of the run in total, and the walker makes little progress.",
                    torque_limit_nm=sc.drive.max_torque, time_at_limit_s=limit_time, time_at_limit_share=limit_time / max(duration, 1e-9), times_at_limit=len(limit_events), advance_efficiency=efficiency)
    if "loop_open" in kinds:
        e = next(e for e in events if e["kind"] == "loop_open")
        add("loop_constraints_opened", "error", f"A loop of the linkage opened by {e['detail']['opening_m'] * 1000:.1f} mm at t = {e['t']:.2f} s: the model has come apart, so the numbers after that are not trustworthy.",
            first_time_s=e["t"], opening_m=e["detail"]["opening_m"])
    slips = [e for e in events if e["kind"] == "slip"]
    if slips:
        total = sum(e["detail"]["duration_s"] for e in slips)
        share = total / (max(duration, 1e-9) * sc.walker.legs)  # of all foot-time
        if share > 0.1 and efficiency is not None and efficiency < 0.8:
            add("slipping", "warning", f"Feet slip for {total:.2f} foot-seconds ({share:.0%} of all foot time) and the stride is {efficiency:.0%} of the ideal.", slip_foot_seconds=total, slip_share=share, advance_efficiency=efficiency, events=len(slips))
    pen = m.get("max_penetration")
    if pen is not None and pen > 0.005:
        add("deep_sinkage", "warning", f"Feet sink {pen * 1000:.1f} mm into the ground (soft contact or heavy load).", max_penetration_m=pen)
    if not out and efficiency is not None and efficiency < 0.5:
        add("slow_unexplained", "warning", f"The walker covers only {efficiency:.0%} of its ideal stride, but no blocking, slipping or torque limit was found.", advance_efficiency=efficiency, advanced_m=advanced)
    rank = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda d: rank[d["severity"]])  # stable: within a severity the rules keep their order
    if not out:
        add("ok", "info", "No problem found: the walker advances normally." + (f" Stride is {efficiency:.0%} of the ideal." if efficiency is not None else ""),
            advance_efficiency=efficiency, advanced_m=advanced, duration_s=duration)
    return out
