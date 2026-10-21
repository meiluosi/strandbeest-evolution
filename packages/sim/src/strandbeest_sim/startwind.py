"""W-03: the lowest constant wind at which a sail-driven walker starts by itself (docs/WIND.md section 5).

"Starts" means: the crank completes one revolution within `max_time` seconds of simulated time. Near the threshold the walker creeps
over the worst crank angle for a long time, so the answer depends logarithmically on `max_time`; it is part of the definition and is
returned with the result. The search assumes that a stronger wind never makes starting harder (monotone in the wind); this is not
checked beyond the bracket, and the ends of the bracket are reported, so a result is an interval, never a bare number.

The simulation is injected (`attempt`) so the search logic is tested without MuJoCo; `simulate_attempt` is the real one."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from strandbeest_common import Design

from .from_design import scenario_from_design
from .runner import run
from .skeptic import LOOP_OPEN_M

MAX_TIME_S = 40.0  # simulated seconds allowed for one revolution
GIVE_UP_S = 10.0  # the run is abandoned when the crank has not moved for this long

# (started, details) for one constant wind speed; details carry the numbers behind it
Attempt = Callable[[float], dict[str, Any]]


@dataclass
class StartWind:
    """The start wind lies in (lo, hi]: `lo` is the highest wind tried that did not start, `hi` the lowest that did."""

    lo: float  # 0.0 when even the lowest wind tried started
    hi: float  # inf when none started up to the highest wind tried
    runs: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    @property
    def found(self) -> bool:
        return 0.0 < self.lo and math.isfinite(self.hi)

    @property
    def estimate(self) -> float:
        """Geometric middle of the interval; nan when the bracket is open on either side."""
        return math.sqrt(self.lo * self.hi) if self.found else float("nan")

    @property
    def trusted(self) -> bool:
        """False if any run opened a loop beyond the skeptic's limit (its numbers are then unreliable)."""
        return all(r.get("valid", True) for r in self.runs)

    def as_dict(self) -> dict[str, Any]:
        return {"lo": self.lo, "hi": self.hi, "estimate": self.estimate, "found": self.found, "trusted": self.trusted, "note": self.note, "runs": self.runs}


def find_start_wind(
    attempt: Attempt,
    *,
    guess: float = 0.5,
    rel_tol: float = 0.05,
    w_min: float = 0.02,
    w_max: float = 30.0,
    max_runs: int = 30,
) -> StartWind:
    """Bracket by factors of two from `guess`, then bisect geometrically until hi / lo <= 1 + rel_tol (or `max_runs` simulations)."""
    runs: list[dict[str, Any]] = []
    cache: dict[float, bool] = {}

    def starts(w: float) -> bool:
        if w not in cache:
            r = attempt(w)
            runs.append({"wind": w, **r})
            cache[w] = bool(r["started"])
        return cache[w]

    def done(note: str, lo: float, hi: float) -> StartWind:
        return StartWind(lo, hi, runs, note)

    w = guess
    if starts(w):
        hi = w
        while True:
            w = max(hi / 2, w_min)  # the last step down lands on w_min instead of skipping past it
            if w == hi:
                return done(f"starts even at {hi:.3g} m/s, the lowest wind tried", 0.0, hi)
            if not starts(w):
                lo = w
                break
            hi = w
    else:
        lo = w
        while True:
            w = min(lo * 2, w_max)
            if w == lo:
                return done(f"does not start up to {lo:.3g} m/s, the highest wind tried", lo, float("inf"))
            if starts(w):
                hi = w
                break
            lo = w

    while hi / lo > 1 + rel_tol and len(runs) < max_runs:
        mid = math.sqrt(lo * hi)
        if starts(mid):
            hi = mid
        else:
            lo = mid
    return done("" if hi / lo <= 1 + rel_tol else f"stopped after {len(runs)} simulations with hi/lo = {hi / lo:.3f}", lo, hi)


def simulate_attempt(
    design: Design,
    overrides: dict[str, Any] | None = None,
    *,
    backend: str = "mujoco",
    max_time: float = MAX_TIME_S,
    give_up: float = GIVE_UP_S,
) -> Attempt:
    """The attempt: sail drive, constant wind. `backend` selects the physics backend ("mujoco" or "k2").
    `overrides` are scenario sections as for `scenario_from_design` (e.g. {"drive": {"crank_friction": 0.004}}).
    """

    def attempt(wind: float) -> dict[str, Any]:
        ov = {k: dict(v) for k, v in (overrides or {}).items()}
        ov.setdefault("drive", {})["kind"] = "sail"
        ov["wind"] = {**ov.get("wind", {}), "kind": "constant", "speed": wind}
        ov["run"] = {**ov.get("run", {}), "revolutions": 1.0, "settle": 0.5, "give_up_after": give_up, "max_time": max_time, "frame_rate": 0}
        r = run(scenario_from_design(design, ov), backend=backend)
        return {
            "started": not r.stalled,
            "time_s": float(r.t[-1]),
            "distance_m": float(r.x[-1] - r.x[0]),
            "valid": bool(r.metrics["max_loop_violation"] < LOOP_OPEN_M),
        }

    return attempt
