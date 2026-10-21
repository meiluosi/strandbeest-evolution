"""V-06: check a community Measurement submission and report what it can be used for.

A community submission is a Measurement document (schemas/measurement.schema.json) produced by a
stranger on their own build of a Strandbeest.  This module answers two questions:

1. Is the document a valid Measurement, and does it carry the metadata a physical measurement
   needs -- instrument, calibration, date, units, raw data, uncertainty and a licence statement?
2. Which quantities can the project use, and at which evidence level (docs/VALIDATION.md)?

The report reuses the vocabulary of the rig's raw-CSV -> Measurement quality report
(packages/rig/src/strandbeest_rig/convert.py): sample rate, duration, revolutions, mean crank
speed and its coefficient of variation, dropouts and a list of warnings.  Where the method is the
same the rig's thresholds are reused; where it is not (a hand measurement is not an encoder log)
they are relaxed, and every threshold is listed in docs/HOW-TO-MEASURE.md.

The JSON Schema itself is not re-implemented here: the document is checked with the repository's
own validator (strandbeest_common.schemas.validate).

Usage:
    from strandbeest_calib import validate_submission
    report = validate_submission(doc, design=design_doc)
    print(report.render())
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Union

import numpy as np

from strandbeest_common import Design, gait_metrics
from strandbeest_common.schemas import validate

# --- The contract the Measurement schema fixes --------------------------------------------

#: Units the Measurement contract fixes for the channels and condition fields it defines.
UNIT_CONTRACT: dict[str, str] = {
    "t": "s",
    "psi": "rad",
    "torque": "N*m",
    "x": "m",
    "wind": "m/s",
    "omega_rad_s": "rad/s",
    "wind_m_s": "m/s",
}

#: Spellings accepted for a unit, normalised to the contract spelling.
UNIT_ALIASES: dict[str, str] = {
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "rad": "rad",
    "radian": "rad",
    "radians": "rad",
    "n*m": "N*m",
    "nm": "N*m",
    "n.m": "N*m",
    "m": "m",
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
    "m/s": "m/s",
    "mps": "m/s",
    "rad/s": "rad/s",
    "rads/s": "rad/s",
}

#: What a submitter may state about the licence of the data.  The project's own licence for
#: contributed data is still undecided (docs/LICENSING.md), so "pending" is a valid answer.
LICENCE_CHOICES: tuple[str, ...] = ("CC0-1.0", "CC-BY-4.0", "all-rights-reserved", "pending")

#: The quantities a physical measurement can contribute, and where their value comes from.
QUANTITIES: tuple[tuple[str, str, str, bool], ...] = (
    # key, label, where the value lives, is it a channel of "channels"
    ("psi", "crank angle psi(t)", "channels/psi", True),
    ("omega_rad_s", "crank speed", "conditions/omega_rad_s", False),
    ("torque", "crank torque tau(t)", "channels/torque", True),
    ("x", "body position x(t) and the stride per revolution", "channels/x", True),
    ("wind_m_s", "wind speed at the walker", "conditions/wind_m_s", False),
)

# Thresholds.  The rig's own numbers are kept where the method is the same; a community
# measurement may come from a phone video, so the sample-rate and revolution floors are lower.
MIN_SAMPLE_RATE_HZ = 10.0  # the rig wants 100 Hz; a 10 Hz log still resolves the crank phase
MIN_REVOLUTIONS = 3.0  # the first revolution is the start-up transient and is discarded
MAX_SPEED_CV = 0.15  # std/mean of the crank speed over 0.1 s windows
MAX_SPEED_MISMATCH = 0.15  # measured crank speed vs conditions/omega_rad_s
MAX_STRIDE_M = 2.0  # no Strandbeest leg reaches this far per revolution
STRIDE_REACH_FACTOR = 1.2  # how far past the leg's reach a stride may be before it is suspicious
MAX_TORQUE_NM = 10.0  # no printed walker needs this much crank torque


@dataclass
class CommunityReport:
    """The outcome of checking one community submission.

    ``errors`` are hard failures: the submission is rejected.  ``warnings`` are suspicions a
    human should read before trusting the data.  ``present`` lists the quantities that are
    recorded and documented well enough to support an evidence level, ``weak`` those that are
    recorded but not documented well enough, and ``missing`` those that are absent.
    """

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    e3_for: list[str] = field(default_factory=list)
    e3_gaps: list[str] = field(default_factory=list)
    evidence_level: str = "E0"

    def asdict(self) -> dict[str, Any]:
        """The report as a plain dictionary (for --json output and for tests)."""
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "present": list(self.present),
            "weak": list(self.weak),
            "missing": list(self.missing),
            "quality": dict(self.quality),
            "e3_for": list(self.e3_for),
            "e3_gaps": list(self.e3_gaps),
            "evidence_level": self.evidence_level,
        }

    def render(self) -> str:
        """The report as text."""
        lines = [f"verdict: {'ACCEPTED' if self.ok else 'REJECTED'} ({len(self.errors)} error(s))"]
        if self.e3_for:
            lines.append(f"evidence level: E3 for {', '.join(self.e3_for)}")
        else:
            lines.append("evidence level: E0 -- no quantity of this submission reaches E3 yet")
        if self.quality:
            lines.append("quality: " + ", ".join(f"{k}={v}" for k, v in self.quality.items()))
        for title, items in (
            ("present", self.present),
            ("present but weak", self.weak),
            ("missing", self.missing),
            ("errors", self.errors),
            ("warnings", self.warnings),
        ):
            if items:
                lines.append(f"{title}:")
                lines.extend(f"  - {item}" for item in items)
        return "\n".join(lines)


def _numbers(value: Any) -> list[float] | None:
    """The values of a channel as floats, or None when the channel is missing or not numeric."""
    if not isinstance(value, list):
        return None
    out: list[float] = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        out.append(float(v))
    return out


def _normalise_unit(unit: str) -> str:
    """Lower-case a unit spelling and fold the typographic variants."""
    return unit.strip().lower().replace("·", "*").replace(" ", "").replace("**", "*")


def _windowed_speed(t: np.ndarray, psi: np.ndarray, win: float = 0.1) -> tuple[float, float]:
    """Mean crank speed and its coefficient of variation over 0.1 s windows.

    Mirrors ``packages/rig/src/strandbeest_rig/convert.py`` (_windowed_speed): the first second is
    skipped so the start-up transient does not dominate the mean.
    """
    edges = np.arange(t[0], t[-1], win)
    mids: list[float] = []
    speeds: list[float] = []
    for a, b in zip(edges[:-1], edges[1:]):
        i, j = np.searchsorted(t, a), np.searchsorted(t, b)
        if j - i >= 2 and t[j - 1] > t[i]:
            mids.append(0.5 * (a + b))
            speeds.append((psi[j - 1] - psi[i]) / (t[j - 1] - t[i]))
    if not speeds:
        # too few samples for a 0.1 s window (a hand measurement may have only two points): use the overall speed
        span = float(t[-1] - t[0])
        return (float((psi[-1] - psi[0]) / span) if span > 0 else 0.0), 0.0
    steady = [s for m, s in zip(mids, speeds) if m > t[0] + 1.0] or speeds
    mean = float(np.mean(steady))
    cv = float(np.std(steady) / abs(mean)) if len(steady) > 3 and abs(mean) > 1e-9 else 0.0
    return mean, cv


def _design_reach_m(design: Union[dict[str, Any], Design, None]) -> float | None:
    """The horizontal reach of a design's foot path in metres, or None when it cannot be computed."""
    if design is None:
        return None
    try:
        d = design if isinstance(design, Design) else Design.load(design)
        g = gait_metrics(d.spec)
        unit_m = float(d.walker.get("unit_m", 0.0))
    except Exception:  # a design we cannot load simply has no known reach
        return None
    if not g.assembled or unit_m <= 0:
        return None
    return g.width * unit_m


def _schema_errors(doc: dict[str, Any], report: CommunityReport) -> set[str]:
    """Validate the document against the Measurement schema; return the paths that failed."""
    paths: set[str] = set()
    try:
        validate("measurement", doc)
    except ValueError as exc:
        for line in str(exc).splitlines()[1:]:
            text = line.strip()
            if not text:
                continue
            path, _, message = text.partition(": ")
            report.errors.append(f"schema: {path}: {message}")
            paths.add(path)
        report.ok = False
    return paths


def validate_submission(
    doc: Any, *, design: Union[dict[str, Any], Design, None] = None
) -> CommunityReport:
    """Check one community Measurement submission and describe what it can be used for.

    ``design`` is the design the submission claims to measure (a Design or its document).  When it
    is given, the stride is checked against that design's leg reach; when it is not, a generic
    limit is used instead.
    """
    report = CommunityReport(ok=True)
    if not isinstance(doc, dict):
        report.errors.append("the submission must be a JSON object")
        report.ok = False
        return report

    schema_paths = _schema_errors(doc, report)

    channels = doc.get("channels") if isinstance(doc.get("channels"), dict) else {}
    conditions = doc.get("conditions") if isinstance(doc.get("conditions"), dict) else {}
    provenance = doc.get("provenance") if isinstance(doc.get("provenance"), dict) else {}
    calibration = provenance.get("calibration") if isinstance(provenance.get("calibration"), dict) else {}
    synthetic = bool(doc.get("synthetic"))

    # --- channels -----------------------------------------------------------------------
    tv = _numbers(channels.get("t"))
    n = len(tv) if tv else 0
    if tv is None and "channels/t" not in schema_paths:
        report.errors.append("channels/t: the time base is missing or is not a list of numbers")
    elif tv is not None:
        if n < 2 and "channels/t" not in schema_paths:
            report.errors.append(f"channels/t: only {n} sample(s); at least 2 are needed to define a rate")
        elif n >= 2:
            dt = np.diff(np.array(tv))
            if np.any(dt <= 0):
                report.errors.append("channels/t: the timestamps must increase strictly; they must not repeat or go backwards")

    for name in sorted(channels):
        values = channels[name]
        if name == "t" or not isinstance(values, list):
            continue
        if len(values) != n and f"channels/{name}" not in schema_paths:
            report.errors.append(
                f"channels/{name}: {len(values)} values but channels/t has {n}; every channel must be sampled at the same instants"
            )
        if name not in UNIT_CONTRACT:
            report.warnings.append(
                f"channels/{name}: not a channel the Measurement contract defines; the calibration machinery ignores it"
            )

    if "psi" not in channels and not synthetic and "channels/psi" not in schema_paths:
        report.errors.append(
            "channels/psi: a physical measurement must record the crank angle; without it the crank phase "
            "cannot be aligned and nothing can be compared with a simulation"
        )

    # --- units the contract fixes ------------------------------------------------------
    _check_magnitudes(channels, tv, report, schema_paths)
    _check_declared_units(calibration, report)

    # --- provenance ---------------------------------------------------------------------
    shared_gaps = _provenance_gaps(provenance, calibration, synthetic, report)
    if provenance and not provenance.get("source"):
        report.errors.append("provenance/source is missing: a provenance record must say where the numbers came from")

    # --- quality numbers ----------------------------------------------------------------
    stated = doc.get("quality") if isinstance(doc.get("quality"), dict) else {}
    quality = _quality(channels, tv, conditions, stated, design, report)
    report.quality = quality

    # --- what the submission can support -------------------------------------------------
    _quantities(channels, conditions, calibration, shared_gaps, synthetic, report)

    if report.errors:
        report.ok = False
        report.evidence_level = "E0"
        report.e3_for = []
    elif report.e3_for:
        report.evidence_level = "E3"
    else:
        report.evidence_level = "E0"
    return report


def _check_magnitudes(channels: dict[str, Any], tv: list[float] | None, report: CommunityReport, schema_paths: set[str]) -> None:
    """Reject values that cannot be the unit the contract fixes for their channel."""
    if tv and len(tv) >= 2:
        duration = tv[-1] - tv[0]
        if duration > 86400 and "channels/t" not in schema_paths:
            report.errors.append(
                f"channels/t: the record spans {duration:.0f} s; a measurement lasts minutes, and the contract "
                "fixes this channel in seconds -- the values look like milliseconds"
            )

    pv = _numbers(channels.get("psi"))
    if pv and len(pv) >= 2:
        sweep = abs(pv[-1] - pv[0])
        if sweep > 200 and "channels/psi" not in schema_paths:
            report.errors.append(
                f"channels/psi: the crank turns {sweep:.0f} rad over the record; a run is a few revolutions. "
                "The contract fixes this channel in radians -- the values look like degrees or encoder counts"
            )

    qv = _numbers(channels.get("torque"))
    if qv:
        peak = max(abs(v) for v in qv)
        if peak > MAX_TORQUE_NM and "channels/torque" not in schema_paths:
            report.errors.append(
                f"channels/torque: peak {peak:.3g} N*m; the contract fixes this channel in N*m and no printed "
                "walker needs more than about 10 N*m -- the values look like a raw count or millinewton-metres"
            )

    xv = _numbers(channels.get("x"))
    if xv and len(xv) >= 2:
        travel = abs(xv[-1] - xv[0])
        if travel > 100 and "channels/x" not in schema_paths:
            report.errors.append(
                f"channels/x: the body travels {travel:.3g} m over the record; a Strandbeest walks metres, not "
                "hundreds -- the contract fixes this channel in metres, so the values look like millimetres"
            )

    wv = _numbers(channels.get("wind"))
    if wv and max(abs(v) for v in wv) > 200 and "channels/wind" not in schema_paths:
        report.errors.append(
            f"channels/wind: peak {max(abs(v) for v in wv):.3g} m/s; the contract fixes this channel in m/s (a "
            "storm is 40 m/s) -- the values look like km/h"
        )


def _check_declared_units(calibration: dict[str, Any], report: CommunityReport) -> None:
    """Reject a declared unit that contradicts the unit the contract fixes."""
    units = calibration.get("units")
    if not isinstance(units, dict):
        return
    for key, declared in sorted(units.items()):
        want = UNIT_CONTRACT.get(key)
        if want is None:
            report.warnings.append(
                f"provenance/calibration/units/{key}: not a quantity the Measurement contract defines; the declaration is ignored"
            )
            continue
        if not isinstance(declared, str):
            report.errors.append(f"provenance/calibration/units/{key}: the declared unit must be a string")
            continue
        got = UNIT_ALIASES.get(_normalise_unit(declared))
        if got is None:
            report.errors.append(
                f"provenance/calibration/units/{key}: '{declared}' is not a unit the contract knows; this quantity is measured in {want}"
            )
        elif got != want:
            report.errors.append(
                f"provenance/calibration/units/{key}: declared as '{declared}' but the contract fixes this quantity "
                f"in {want}; convert the data or declare the contract unit"
            )


def _provenance_gaps(
    provenance: dict[str, Any], calibration: dict[str, Any], synthetic: bool, report: CommunityReport
) -> list[str]:
    """The submission-level requirements for an evidence level; returns the ones that are unmet."""
    gaps: list[str] = []
    if synthetic:
        gaps.append("the document is declared synthetic: a simulated record is not a physical measurement")
    source = provenance.get("source")
    if not provenance:
        gaps.append("provenance is missing: the numbers cannot be traced to where they came from")
    elif not source:
        pass  # reported as an error by the caller
    elif source == "simulator":
        gaps.append("provenance/source is 'simulator': this is not a physical measurement")
    if not calibration.get("instrument"):
        gaps.append("provenance/calibration/instrument is missing: the measuring device is unknown")
    if not calibration.get("measured_on"):
        gaps.append("provenance/calibration/measured_on is missing: the date of the measurement is unknown")
    calibrated_on = calibration.get("calibrated_on")
    if not calibrated_on:
        gaps.append("provenance/calibration/calibrated_on is missing: the instrument's calibration is unknown")
    elif not str(calibrated_on).startswith(("19", "20")):
        report.warnings.append(
            f"provenance/calibration/calibrated_on: '{calibrated_on}' does not look like a date (YYYY-MM-DD)"
        )
    licence = calibration.get("licence")
    if not licence:
        gaps.append(
            "provenance/calibration/licence is missing: state under which licence the data may be used "
            "(see docs/LICENSING.md; the project's licence for contributed data is still undecided)"
        )
    elif licence not in LICENCE_CHOICES:
        gaps.append(
            f"provenance/calibration/licence: '{licence}' is not one of {', '.join(LICENCE_CHOICES)}"
        )
    elif licence == "pending":
        gaps.append("the licence statement is 'pending': the contributor has not decided yet")
    if not provenance.get("raw_file"):
        gaps.append("provenance/raw_file is missing: the raw data behind the numbers is not referenced")
    return gaps


def _quality(
    channels: dict[str, Any],
    tv: list[float] | None,
    conditions: dict[str, Any],
    stated: dict[str, Any],
    design: Union[dict[str, Any], Design, None],
    report: CommunityReport,
) -> dict[str, Any]:
    """The numeric part of the report, in the rig's vocabulary."""
    quality: dict[str, Any] = {}
    pv = _numbers(channels.get("psi"))
    qv = _numbers(channels.get("torque"))
    xv = _numbers(channels.get("x"))

    for warning in stated.get("warnings", []) or []:
        report.warnings.append(f"the submission carries its own converter warning: {warning}")

    if tv and len(tv) >= 2:
        dt = np.diff(np.array(tv))
        med = float(np.median(dt))
        rate = 1.0 / med if med > 0 else 0.0
        quality["sample_rate_hz"] = round(rate, 2)
        quality["duration_s"] = round(float(tv[-1] - tv[0]), 3)
        quality["dropouts"] = int(np.sum(dt > 3 * med)) if med > 0 else 0
        if rate < MIN_SAMPLE_RATE_HZ:
            report.warnings.append(
                f"sample rate {rate:.2f} Hz is low; aim for at least {MIN_SAMPLE_RATE_HZ:.0f} Hz so the crank phase is resolved"
            )
        if quality["dropouts"]:
            report.warnings.append(
                f"{quality['dropouts']} gaps longer than 3x the median sample interval (dropped frames?)"
            )

    if pv and len(pv) >= 2:
        revs = abs(pv[-1] - pv[0]) / (2 * math.pi)
        quality["revolutions"] = round(revs, 3)
        if pv[-1] < pv[0]:
            report.warnings.append(
                "crank angle decreases: psi must increase in the walking direction, so the sign is probably wrong"
            )
        if revs < MIN_REVOLUTIONS:
            report.warnings.append(
                f"only {revs:.1f} crank revolutions; use at least {MIN_REVOLUTIONS:.0f} so the first (start-up) revolution can be discarded"
            )
        if tv and len(tv) >= 2:
            mean, cv = _windowed_speed(np.array(tv), np.array(pv))
            quality["speed_mean_rad_s"] = round(mean, 4)
            quality["speed_cv"] = round(cv, 4)
            if cv > MAX_SPEED_CV:
                report.warnings.append(
                    f"crank speed varies by {cv * 100:.0f} % (std/mean): the walker was not driven at a constant "
                    "speed, so a quasi-static comparison suffers"
                )
            target = conditions.get("omega_rad_s")
            if isinstance(target, (int, float)) and not isinstance(target, bool) and abs(mean) > 1e-9:
                if abs(abs(mean) - abs(float(target))) / abs(float(target)) > MAX_SPEED_MISMATCH:
                    report.warnings.append(
                        f"mean crank speed {abs(mean):.2f} rad/s differs from the stated {float(target):.2f} rad/s "
                        f"by more than {MAX_SPEED_MISMATCH * 100:.0f} %"
                    )

    if qv:
        quality["torque_mean_nm"] = round(float(np.mean(qv)), 6)
        quality["torque_max_nm"] = round(float(np.max(np.abs(qv))), 6)
        if all(v <= 0 for v in qv):
            report.warnings.append("torque is never positive: the sign of the torque channel may be inverted")

    if xv and len(xv) >= 2 and quality.get("revolutions"):
        stride = (xv[-1] - xv[0]) / float(quality["revolutions"])
        quality["stride_m"] = round(float(stride), 5)
        reach = _design_reach_m(design)
        if reach:
            if stride > STRIDE_REACH_FACTOR * reach:
                report.warnings.append(
                    f"the stride is {stride:.3f} m per crank revolution but the referenced design's foot path "
                    f"spans only {reach:.3f} m: the stride exceeds the leg's reach"
                )
        elif stride > MAX_STRIDE_M:
            report.warnings.append(
                f"the stride is {stride:.3f} m per crank revolution; no Strandbeest leg reaches that far -- "
                "check the unit of 'x' and the design it refers to"
            )

    stated_revs = stated.get("revolutions")
    if (
        isinstance(stated_revs, (int, float))
        and not isinstance(stated_revs, bool)
        and quality.get("revolutions")
        and abs(float(stated_revs) - float(quality["revolutions"])) > 0.05 * max(float(quality["revolutions"]), 1.0)
    ):
        report.warnings.append(
            f"the stated quality block says {float(stated_revs):.2f} revolutions but the channels hold "
            f"{float(quality['revolutions']):.2f}"
        )
    return quality


def _quantities(
    channels: dict[str, Any],
    conditions: dict[str, Any],
    calibration: dict[str, Any],
    shared_gaps: list[str],
    synthetic: bool,
    report: CommunityReport,
) -> None:
    """Sort every quantity into present / present but weak / missing, and decide the evidence level."""
    units = calibration.get("units") if isinstance(calibration.get("units"), dict) else {}
    uncertainty = calibration.get("uncertainty") if isinstance(calibration.get("uncertainty"), dict) else {}

    for key, label, where, is_channel in QUANTITIES:
        if is_channel:
            values = _numbers(channels.get(key))
            has_value = values is not None and len(values) >= 2
        else:
            value = conditions.get(key)
            has_value = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not has_value:
            report.missing.append(f"{label} ({where})")
            continue

        why: list[str] = []
        if is_channel:
            declared = units.get(key)
            if declared is None:
                why.append("the unit is not declared")
            else:
                got = UNIT_ALIASES.get(_normalise_unit(str(declared)))
                if got != UNIT_CONTRACT[key]:
                    why.append(f"the declared unit '{declared}' is not the contract unit {UNIT_CONTRACT[key]}")
        err = uncertainty.get(key)
        if err is None:
            why.append("no error estimate is recorded")
        elif not isinstance(err, (int, float)) or isinstance(err, bool) or err <= 0:
            why.append(f"the recorded error estimate ({err!r}) is not a positive number")

        if why:
            report.weak.append(f"{label} ({where}): " + "; ".join(why))
        else:
            report.present.append(f"{label} ({where})")
        blockers = [f"{label}: {w}" for w in why] + list(shared_gaps)
        if blockers:
            for blocker in blockers:
                _add_gap(report, blocker)
        else:
            report.e3_for.append(label)


def _add_gap(report: CommunityReport, gap: str) -> None:
    """Record a reason why a quantity does not reach an evidence level (keeping the order, without repeats)."""
    if gap not in report.e3_gaps:
        report.e3_gaps.append(gap)
