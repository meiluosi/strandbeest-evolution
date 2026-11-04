"""Audit net-extraction cases the legacy positive-input share metric omits.

Use the same windows, unmodified trajectories and 2% threshold. Preserve the
original audit; this additional signed-work check is explicitly separate.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from strandbeest_sim import run
from strandbeest_sim.skeptic import ENERGY_RESIDUAL


def main():
    output = Path(sys.argv[1])
    if output.exists():
        raise FileExistsError(output)
    rows = []
    for name in sys.argv[2:]:
        source = json.loads(Path(name).read_text())
        assert source["complete"]
        for original in source["rows"]:
            if "energy_residual_share" in original["metrics"]:
                continue
            result = run(original["scenario"])
            psi, rev = result.psi, 2 * math.pi
            total = (psi[-1] - psi[0]) / rev
            if total >= 1.98:
                n = max(1, math.floor(total + .02) - 1)
                lo, hi = rev, min(rev * (1 + n), psi[-1])
            else:
                lo, hi = 0, psi[-1]
            indices = np.flatnonzero((psi >= lo) & (psi <= hi))
            first, last = int(indices[0]), int(indices[-1])
            s = result.series
            delta = {key: float(s[key][last] - s[key][first]) for key in
                     ("e_in", "e_contact", "e_loops", "e_friction", "kinetic", "potential")}
            residual = delta["e_in"] - sum(delta[k] for k in ("e_contact", "e_loops", "e_friction", "kinetic", "potential"))
            ratio = residual / abs(delta["e_in"]) if abs(delta["e_in"]) > 1e-12 else None
            row = {"cohort": name, "case": original["case"], "legacy_metric_missing": True,
                   "window": {"first": first, "last": last, "t_start": float(result.t[first]), "t_end": float(result.t[last])},
                   "energy_delta_j": delta, "residual_j": residual,
                   "residual_over_abs_net_input": ratio, "threshold": ENERGY_RESIDUAL,
                   "passed": ratio is not None and abs(ratio) <= ENERGY_RESIDUAL}
            rows.append(row)
            print(json.dumps(row), flush=True)
    with output.open("x") as f:
        json.dump({"definition": "Signed energy balance; magnitude normalized by absolute net input. Separate from unchanged legacy audit.",
                   "rows": rows, "all_checked_pass": all(r["passed"] for r in rows)}, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
