"""Raw rig CSV -> Measurement document, with quality checks.

Raw format (what the firmware prints, one line per sample):
    # key=value ...            comment / metadata lines (ignored except for the record)
    t_ms,enc,current_mA,load_raw,wind_pulses,pwm
`t_ms` and `enc` are required; the other columns are optional and may be empty. `enc` is the signed quadrature count of the
motor shaft; `wind_pulses` is cumulative.
"""

from __future__ import annotations

import io
import math
from typing import Any

import numpy as np

from strandbeest_common.schemas import validate

from .calibration import G, Calibration

REQUIRED = ("t_ms", "enc")


def parse_raw(text: str) -> tuple[dict[str, np.ndarray], list[str]]:
    """Return columns as float arrays (NaN where empty) and the comment lines."""
    comments: list[str] = []
    rows: list[list[str]] = []
    header: list[str] | None = None
    for line in io.StringIO(text):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comments.append(line.lstrip("# ").strip())
            continue
        parts = [p.strip() for p in line.split(",")]
        if header is None:
            header = parts
            missing = [c for c in REQUIRED if c not in header]
            if missing:
                raise ValueError(f"raw file is missing required columns {missing}; header was {header}")
            continue
        if len(parts) != len(header):
            continue  # a truncated line from a serial glitch: skip it, the dropout count will show it
        rows.append(parts)
    if header is None or not rows:
        raise ValueError("raw file has no data rows")
    cols: dict[str, np.ndarray] = {}
    for i, name in enumerate(header):
        vals = []
        for r in rows:
            try:
                vals.append(float(r[i]) if r[i] != "" else math.nan)
            except ValueError:
                vals.append(math.nan)
        cols[name] = np.array(vals)
    # unwrap a 32-bit millisecond counter
    t = cols["t_ms"]
    wraps = np.cumsum(np.concatenate([[0], (np.diff(t) < -(2**31))])) * 2**32
    cols["t_ms"] = t + wraps
    return cols, comments


def _windowed_speed(t: np.ndarray, psi: np.ndarray, win: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
    """Crank speed over non-overlapping windows of `win` seconds: (window mid times, rad/s)."""
    edges = np.arange(t[0], t[-1], win)
    mids, speeds = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        i, j = np.searchsorted(t, a), np.searchsorted(t, b)
        if j - i >= 2 and t[j - 1] > t[i]:
            mids.append(0.5 * (a + b))
            speeds.append((psi[j - 1] - psi[i]) / (t[j - 1] - t[i]))
    return np.array(mids), np.array(speeds)


def quality_report(t: np.ndarray, psi: np.ndarray, torque: np.ndarray | None, cal: Calibration, omega_target: float | None) -> dict[str, Any]:
    dt = np.diff(t)
    med = float(np.median(dt)) if len(dt) else 0.0
    rate = 1.0 / med if med > 0 else 0.0
    dropouts = int(np.sum(dt > 3 * med)) if med > 0 else 0
    revs = float(abs(psi[-1] - psi[0]) / (2 * math.pi))
    mids, speeds = _windowed_speed(t, psi)
    steady = speeds[mids > t[0] + 1.0] if len(speeds) else speeds
    mean = float(np.mean(steady)) if len(steady) else 0.0
    cv = float(np.std(steady) / abs(mean)) if len(steady) > 3 and abs(mean) > 1e-9 else 0.0
    warnings: list[str] = []
    if rate < 50:
        warnings.append(f"sample rate {rate:.0f} Hz is low; aim for at least 100 Hz")
    if dropouts:
        warnings.append(f"{dropouts} gaps longer than 3x the median sample interval (serial dropouts?)")
    if revs < 3:
        warnings.append(f"only {revs:.1f} crank revolutions; use at least 3 so the first (start-up) revolution can be discarded")
    if psi[-1] < psi[0]:
        warnings.append("crank angle decreases: the encoder direction in the calibration is probably wrong")
    if cv > 0.15:
        warnings.append(f"crank speed varies by {cv * 100:.0f} % (std/mean): the rig is not holding constant speed, quasi-static comparisons suffer")
    if omega_target and abs(mean) > 0 and abs(abs(mean) - omega_target) / omega_target > 0.15:
        warnings.append(f"mean crank speed {abs(mean):.2f} rad/s differs from the stated {omega_target:.2f} rad/s by more than 15 %")
    if torque is not None and np.all(torque <= 0):
        warnings.append("torque is never positive: sign of the current/load-cell channel may be inverted")
    if cal.torque_method == "current" and cal.idle_current_ma == 0:
        warnings.append("idle current is 0: motor and gearbox friction are included in the torque")
    if not cal.calibrated:
        warnings.append("calibration is not marked as calibrated; constants are datasheet or default guesses")
    return {
        "sample_rate_hz": round(rate, 2),
        "duration_s": round(float(t[-1] - t[0]), 3),
        "revolutions": round(revs, 3),
        "speed_mean_rad_s": round(mean, 4),
        "speed_cv": round(cv, 4),
        "dropouts": dropouts,
        "time_offset_s": None,
        "warnings": warnings,
    }


def _progress_time(t: np.ndarray, v: np.ndarray, frac: float) -> float | None:
    """First time the signal has covered `frac` of its total displacement (monotonic-ish ramps)."""
    total = v[-1] - v[0]
    if abs(total) < 1e-9:
        return None
    prog = (v - v[0]) / total
    hit = np.where(prog >= frac)[0]
    return float(t[hit[0]]) if len(hit) else None


def align_offset(t: np.ndarray, psi: np.ndarray, tt: np.ndarray, xx: np.ndarray) -> tuple[float | None, float]:
    """Seconds to add to the video clock so it matches the encoder clock, and the spread of the estimates.

    Both signals are ramps that start together (the walker starts moving when the crank does), and x is roughly proportional to
    psi, so the times at which each has covered 5 %, 10 % and 20 % of its range should coincide."""
    offs = []
    for f in (0.05, 0.1, 0.2):
        a, b = _progress_time(t, psi, f), _progress_time(tt, xx, f)
        if a is not None and b is not None:
            offs.append(a - b)
    if not offs:
        return None, 0.0
    return float(np.mean(offs)), float(np.max(offs) - np.min(offs))


def convert_raw(
    text: str,
    cal: Calibration,
    *,
    id: str,
    design_name: str,
    kind: str = "motor_no_wind",
    omega_rad_s: float | None = None,
    wind_m_s: float | None = None,
    surface: str = "",
    build_note: str = "",
    raw_name: str = "",
    track: tuple[np.ndarray, np.ndarray] | None = None,
    track_offset_s: float | None = None,
) -> dict[str, Any]:
    cols, comments = parse_raw(text)
    t = (cols["t_ms"] - cols["t_ms"][0]) / 1000.0
    enc = cols["enc"]
    psi = cal.direction * (enc - enc[0]) / cal.counts_per_motor_rev / cal.gear_ratio * 2 * math.pi

    channels: dict[str, list[float]] = {"t": t.tolist(), "psi": psi.tolist()}
    torque = None
    if cal.torque_method == "current" and "current_mA" in cols and not np.all(np.isnan(cols["current_mA"])):
        torque = (cols["current_mA"] - cal.idle_current_ma) * 1e-3 * cal.kt_nm_per_a
    elif cal.torque_method == "load_cell" and "load_raw" in cols and not np.all(np.isnan(cols["load_raw"])):
        torque = (cols["load_raw"] - cal.zero_counts) / cal.counts_per_gram * 1e-3 * G * cal.arm_m
    if torque is not None:
        ok = ~np.isnan(torque)
        channels["torque"] = np.where(ok, torque, 0.0).tolist() if ok.all() else np.interp(t, t[ok], torque[ok]).tolist()
    if cal.wind_ms_per_hz > 0 and "wind_pulses" in cols and not np.all(np.isnan(cols["wind_pulses"])):
        pulses = cols["wind_pulses"]
        w = np.zeros_like(t)
        for i in range(len(t)):
            j = np.searchsorted(t, t[i] - 1.0)
            span = t[i] - t[j]
            w[i] = (pulses[i] - pulses[j]) / span * cal.wind_ms_per_hz if span > 0.2 else 0.0
        channels["wind"] = w.tolist()
        if wind_m_s is None:
            wind_m_s = float(np.mean(w[t > 1.0])) if np.any(t > 1.0) else None

    q = quality_report(t, psi, None if torque is None else np.array(channels["torque"]), cal, omega_rad_s)

    if track is not None:
        tt, xx = (np.asarray(a, float) for a in track)
        offset = track_offset_s
        spread = 0.0
        if offset is None:
            offset, spread = align_offset(t, psi, tt, xx)
            if offset is None:
                offset = 0.0
                q["warnings"].append("could not find the start of motion in both signals to align video with the encoder; offset set to 0")
        x = np.interp(t, tt + offset, xx, left=np.nan, right=np.nan)
        valid = np.where(~np.isnan(x))[0]
        if len(valid) > 10:
            i0, i1 = int(valid[0]), int(valid[-1]) + 1
            if i0 > 0 or i1 < len(t):
                q["warnings"].append(f"video and encoder overlap only from {t[i0]:.2f} s to {t[i1 - 1]:.2f} s after alignment; all channels were trimmed to that range")
                channels = {k: v[i0:i1] for k, v in channels.items()}
                t_trim = np.array(channels["t"])
                channels["t"] = (t_trim - t_trim[0]).tolist()
                x = x[i0:i1]
            channels["x"] = (x - x[0]).tolist()
            q["time_offset_s"] = round(float(offset), 4)
            if track_offset_s is None:
                q["warnings"].append(f"video aligned to the encoder from the start of motion (estimates agree within {spread:.2f} s)")
                if spread > 0.1:
                    q["warnings"].append("alignment estimates disagree by more than 0.1 s: check that video and rig started together")
        else:
            q["warnings"].append("video tracking does not overlap the encoder data after alignment; x channel dropped")

    cond: dict[str, Any] = {"kind": kind}
    if omega_rad_s is not None:
        cond["omega_rad_s"] = omega_rad_s
    if wind_m_s is not None and kind == "fan":
        cond["wind_m_s"] = max(0.0, wind_m_s)
    if surface:
        cond["surface"] = surface
    doc = {
        "schema_version": 1,
        "id": id,
        "design_name": design_name,
        "synthetic": False,
        "build_note": build_note,
        "conditions": cond,
        "channels": channels,
        "provenance": {
            "source": "rig",
            "rig_version": next((c.split("fw=")[1].split()[0] for c in comments if "fw=" in c), ""),
            "calibration": cal.asdict(),
            "raw_file": raw_name,
            "notes": "; ".join(c for c in comments if "=" not in c)[:500],
        },
        "quality": q,
    }
    if not doc["build_note"]:
        del doc["build_note"]
    validate("measurement", doc)
    return doc
