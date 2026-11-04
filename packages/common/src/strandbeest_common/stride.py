"""Shared Rust geometry-only diagnostic, separate from the production audit.

Inputs are derived from an existing Scenario and the actual built sphere owner;
they introduce no independent physical defaults. The lowest-foot/no-slip model
does not predict compliant contacts or slipping. Compare sampling resolutions.
"""
from __future__ import annotations

import json
from typing import Sequence

from .linkage import LinkageSpec, _kernel


def stride_reference(spec: LinkageSpec, *, owner_start: str, phases_rad: Sequence[float],
                     direction: int, unit_m: float, radius_m: float, brackets: int) -> dict:
    """Signed metres/revolution, or an explicit status with no estimate.

    Invalid input raises ValueError; nonassembly is reported as data. No Python
    numerical fallback and no rounding/flooring of a tiny signed displacement.
    """
    options = dict(owner_start=owner_start, phases_rad=list(phases_rad), direction=direction,
                   unit_m=unit_m, radius_m=radius_m, brackets=brackets)
    return json.loads(_kernel(spec).stride_reference_json(json.dumps(options, allow_nan=False)))
