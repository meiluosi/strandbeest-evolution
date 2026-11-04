"""Configurable MuJoCo dynamics simulator for Strandbeest-style linkage walkers."""

from .builder import EntityBuilt, HerdBuilt, build_herd
from .config import Scenario, SimConfig, load_scenario, sim_config
from .dynamometer import virtual_dynamometer
from .fluids.tide import DynamicTideField
from .from_design import scenario_from_design
from .interactive import InteractiveSession
from .runner import HerdResult, Result, WalkerTrajectory, run, run_herd
from .startwind import find_start_wind, work_energy_start_wind_proxy
from .winds import SpatiotemporalWindField
from . import fluids

__all__ = [
    "Scenario",
    "SimConfig",
    "load_scenario",
    "sim_config",
    "Result",
    "run",
    "scenario_from_design",
    "virtual_dynamometer",
    "find_start_wind",
    "work_energy_start_wind_proxy",
    "InteractiveSession",
    "fluids",
    "EntityBuilt",
    "HerdBuilt",
    "build_herd",
    "DynamicTideField",
    "SpatiotemporalWindField",
    "HerdResult",
    "WalkerTrajectory",
    "run_herd",
]

# importing these modules registers the built-in extensions
from . import drives as _drives  # noqa: E402,F401
from . import metrics_builtin as _metrics  # noqa: E402,F401
from . import terrains as _terrains  # noqa: E402,F401
from . import winds as _winds  # noqa: E402,F401
