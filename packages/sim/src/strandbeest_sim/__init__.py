"""Configurable MuJoCo dynamics simulator for Strandbeest-style linkage walkers."""

from .config import Scenario, load_scenario
from .runner import Result, run

__all__ = ["Scenario", "load_scenario", "Result", "run"]

# importing these modules registers the built-in extensions
from . import drives as _drives  # noqa: E402,F401
from . import metrics_builtin as _metrics  # noqa: E402,F401
from . import terrains as _terrains  # noqa: E402,F401
