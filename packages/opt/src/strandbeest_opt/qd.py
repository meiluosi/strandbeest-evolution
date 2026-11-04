"""Quality-diversity: MAP-Elites archive over walker designs (O-02, M8-01).

Maintains a grid of behavior feature descriptors where each cell holds the highest-fitness individual found.
Supports configurable 2D behavior descriptors:
  - Dimension 1: Obstacle step clearance / lift ratio (z_lift / L).
  - Dimension 2: Cost of transport / energy efficiency or dynamic stability margin (E_transport = P_mean / (m * g * v_mean)).
Also retains backward compatibility with the legacy 3D kinematic archive (legs, stride, mass).

Includes Iso+LineDD crossover (Vassiliades & Mouret 2018), archive analytics (QD-score, coverage, Pareto front),
and SpeciesAtlas schema serialization.
"""

from __future__ import annotations

import copy
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from strandbeest_common import Design
from strandbeest_common.gait import Gait, foot_path, gait_metrics
from strandbeest_common.ids import new_ulid
from strandbeest_common.schemas import validate

from .fitness import fitness_flat_stroke, infeasibility
from .space import GenomeSpace

LEGS = (4, 6, 8, 10, 12)
STRIDE_BINS = np.linspace(0.05, 0.45, 9)  # m per revolution: 8 bins
MASS_BINS = np.linspace(0.30, 1.50, 7)  # kg: 6 bins


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Elite:
    cell: tuple[int, ...]
    fitness: float
    genome: list[float]
    legs: int
    stride_m: float
    mass_kg: float
    parent: tuple[int, ...] | None
    born: int  # evaluation index at which it entered the archive
    features: dict[str, float] = field(default_factory=dict)

    @property
    def lift_ratio(self) -> float:
        return self.features.get("lift_ratio", 0.0)

    @property
    def cost_of_transport(self) -> float:
        return self.features.get("cost_of_transport", 0.0)


def _bin(v: float, edges: np.ndarray) -> int | None:
    if v < edges[0] or v >= edges[-1]:
        return None
    return int(np.searchsorted(edges, v, side="right") - 1)


# -- Feature descriptor computations ---------------------------------------------------------------------------------


def compute_lift_ratio(gait: Gait) -> float:
    """Obstacle step clearance / lift ratio: z_lift / L where z_lift is foot loop lift and L is foot loop width."""
    return float(gait.lift / max(1e-4, gait.width))


def compute_cost_of_transport(
    base: dict[str, Any],
    spec: Any,
    gait: Gait,
    foot: list[tuple[float, float]],
    legs: int,
    joint_friction: float = 0.005,
) -> float:
    """Cost of transport / specific resistance: E_transport = P_mean / (m * g * v_mean).

    For steady-state crank rotation with no regenerative braking:
      P_mean = mean(max(0, tau(theta))) * omega
      v_mean = (stride_m / (2 * pi)) * omega
      E_transport = (2 * pi * mean(max(0, tau))) / (m_total * g * stride_m)
    where tau(theta) is the torque to raise the chassis center-of-mass against gravity plus joint friction.
    """
    unit_m = float(base.get("walker", {}).get("unit_m", 0.002))
    stride_m = float(gait.stroke_length / max(1e-4, gait.duty) * unit_m)
    if stride_m <= 1e-4:
        return float("inf")

    # Mass calculation
    d = Design(base)
    per_leg_m = (spec.crank + sum(spec.val(r) for j in spec.joints for r in j.radii)) * unit_m
    m_body = float(base.get("walker", {}).get("body_mass_kg", 0.35))
    m_total = m_body + legs * per_leg_m * d.bar_mass_per_m()
    g = 9.81
    weight = m_total * g

    k_samples = len(foot)
    thetas = np.linspace(0, 2 * math.pi, k_samples, endpoint=False)

    # Hip height h(theta) is -(lowest foot y in meters)
    h_arr = np.array(
        [-min(foot[(k + int(round(i * k_samples / legs))) % k_samples][1] for i in range(legs)) * unit_m for k in range(k_samples)]
    )
    dh_dpsi = np.gradient(h_arr, thetas)

    # Driving torque to lift the body against gravity plus friction
    tau = weight * dh_dpsi + joint_friction
    tau_pos = np.maximum(0.0, tau)
    mean_tau_pos = float(np.mean(tau_pos))

    # E_transport = (2 * pi * mean(tau_pos)) / (m_total * g * stride_m)
    cot = (2.0 * math.pi * mean_tau_pos) / (weight * stride_m)
    return float(cot)


def compute_stability_margin(
    base: dict[str, Any],
    foot: list[tuple[float, float]],
    legs: int,
    tol_contact: float = 2.0,
) -> float:
    """Dynamic / kinematic stability margin: normalized minimum distance from hip/CoM (x=0) to support edge."""
    k_samples = len(foot)
    unit_m = float(base.get("walker", {}).get("unit_m", 0.002))
    margins = []

    for k in range(k_samples):
        # Gather contact foot positions at this phase
        phases_idx = [(k + int(round(i * k_samples / legs))) % k_samples for i in range(legs)]
        ys = [foot[idx][1] for idx in phases_idx]
        lowest_y = min(ys)
        contact_xs = [foot[idx][0] * unit_m for idx, y in zip(phases_idx, ys) if y <= lowest_y + tol_contact]
        if not contact_xs:
            margins.append(0.0)
            continue
        x_min, x_max = min(contact_xs), max(contact_xs)
        # Margin from CoM at x=0
        margin = min(0.0 - x_min, x_max - 0.0)
        margins.append(margin)

    # Normalize by nominal stride
    min_margin = min(margins) if margins else 0.0
    return float(max(-1.0, min(1.0, min_margin / 0.1)))


def describe(base: dict[str, Any], space: GenomeSpace, genome: list[float], legs: int) -> tuple[float, float] | None:
    """(stride per revolution in m, total mass in kg) of the design with these lengths and leg count; None if infeasible."""
    if infeasibility(space, genome) is not None:
        return None
    spec = space.to_spec(genome)
    g = gait_metrics(spec, 90)
    if g.duty <= 0:
        return None
    unit = base["walker"]["unit_m"]
    stride = g.stroke_length / g.duty * unit
    doc = copy.deepcopy(base)
    doc["linkage"] = space.to_dict(genome)
    doc["walker"]["legs"] = legs
    d = Design(doc)
    per_leg_m = (spec.crank + sum(spec.val(r) for j in spec.joints for r in j.radii)) * unit
    return stride, base["walker"]["body_mass_kg"] + legs * per_leg_m * d.bar_mass_per_m()


def describe_features(
    base: dict[str, Any],
    space: GenomeSpace,
    genome: list[float],
    legs: int,
    descriptors: Sequence[str] = ("lift_ratio", "cost_of_transport"),
) -> dict[str, float] | None:
    """Evaluate behavioral descriptors for MAP-Elites grid binning."""
    if infeasibility(space, genome) is not None:
        return None
    spec = space.to_spec(genome)
    g = gait_metrics(spec, 90)
    if not g.assembled or g.width <= 0 or g.duty <= 0:
        return None
    foot = foot_path(spec, 90)
    if foot is None:
        return None

    unit = base["walker"]["unit_m"]
    stride_m = g.stroke_length / g.duty * unit
    doc = copy.deepcopy(base)
    doc["linkage"] = space.to_dict(genome)
    doc["walker"]["legs"] = legs
    d = Design(doc)
    per_leg_m = (spec.crank + sum(spec.val(r) for j in spec.joints for r in j.radii)) * unit
    mass_kg = base["walker"]["body_mass_kg"] + legs * per_leg_m * d.bar_mass_per_m()

    res: dict[str, float] = {
        "stride_m": float(stride_m),
        "mass_kg": float(mass_kg),
    }

    for name in descriptors:
        if name in ("lift_ratio", "step_clearance", "lift"):
            res[name] = compute_lift_ratio(g)
        elif name in ("cost_of_transport", "transport_cost", "cot", "energy_efficiency"):
            res[name] = compute_cost_of_transport(base, spec, g, foot, legs)
        elif name in ("stability_margin", "dynamic_stability"):
            res[name] = compute_stability_margin(base, foot, legs)
        elif name == "stride":
            res[name] = float(stride_m)
        elif name == "mass":
            res[name] = float(mass_kg)
        else:
            res[name] = 0.0

    return res


# -- Iso+LineDD crossover operator -----------------------------------------------------------------------------------


class IsoLineDDCrossover:
    """Iso+LineDD: Line mutation between two randomly selected elites combined with isotropic Gaussian noise.

    Offspring proposal formula:
        x_new = p1 + sigma_line * (p2 - p1) * N(0, 1) + sigma_iso * abs(p1) * N(0, I)
    When only one parent is available, the line component vanishes and it behaves as an isotropic Gaussian mutation.
    """

    def __init__(
        self,
        sigma_iso: float = 0.02,
        sigma_line: float = 0.15,
        rng: random.Random | None = None,
    ) -> None:
        self.sigma_iso = sigma_iso
        self.sigma_line = sigma_line
        self.rng = rng or random.Random()

    def propose(
        self,
        p1: list[float],
        p2: list[float] | None = None,
        bounds: list[tuple[float, float]] | None = None,
    ) -> list[float]:
        if p2 is not None and len(p1) == len(p2):
            diff = [b - a for a, b in zip(p1, p2)]
            line_eps = self.rng.gauss(0.0, 1.0)
        else:
            diff = [0.0] * len(p1)
            line_eps = 0.0

        offspring: list[float] = []
        for i, (a, d) in enumerate(zip(p1, diff)):
            scale = abs(a) if a != 0.0 else 1.0
            iso_eps = self.rng.gauss(0.0, 1.0)
            val = a + self.sigma_line * d * line_eps + self.sigma_iso * scale * iso_eps
            if bounds and i < len(bounds):
                lo, hi = bounds[i]
                val = min(hi, max(lo, val))
            offspring.append(float(val))
        return offspring


# -- MAP-Elites Archive ----------------------------------------------------------------------------------------------


class MapElites:
    """MAP-Elites quality-diversity archive over Strandbeest linkages.

    Maintains a grid of behavior descriptors and stores the best elite design in every occupied cell.
    Supports 2D behavior feature descriptors:
      1. Obstacle step clearance / lift ratio (z_lift / L)
      2. Cost of transport (E_transport = P_mean / (m * g * v_mean))
    Also supports legacy 3D kinematics (legs, stride, mass) when requested.
    """

    def __init__(
        self,
        base_design: dict[str, Any],
        seed: int = 0,
        sigma: float = 0.06,
        lo: float = 0.7,
        hi: float = 1.4,
        feature_descriptors: Sequence[str] | None = None,
        grid_shape: tuple[int, ...] = (16, 16),
        feature_ranges: dict[str, tuple[float, float]] | None = None,
        legacy_3d: bool | None = None,
        sigma_line: float = 0.15,
    ) -> None:
        self.base = copy.deepcopy(base_design)
        self.space = GenomeSpace.of(base_design["linkage"])
        self.fit = fitness_flat_stroke(self.space)
        self.rng = random.Random(seed)
        self.sigma = sigma
        self.sigma_line = sigma_line

        g0 = self.space.to_genome()
        self.lo = [lo * v for v in g0]
        self.hi = [hi * v for v in g0]
        self.bounds = list(zip(self.lo, self.hi))

        self.crossover = IsoLineDDCrossover(sigma_iso=sigma, sigma_line=sigma_line, rng=self.rng)
        self.archive: dict[tuple[int, ...], Elite] = {}
        self.evals = 0
        self.curve: list[tuple[int, int, float]] = []  # (evaluations, cells filled, QD score)

        # Mode configuration: if feature_descriptors is None and legacy_3d is not False, or feature_descriptors is 3D
        if legacy_3d is True or (legacy_3d is None and feature_descriptors is None) or (feature_descriptors and tuple(feature_descriptors) == ("legs", "stride", "mass")):
            self.legacy_3d = True
            self.feature_descriptors = ("legs", "stride", "mass")
            self.grid_shape = (len(LEGS), len(STRIDE_BINS) - 1, len(MASS_BINS) - 1)
            self.bin_edges = {
                "stride": STRIDE_BINS,
                "mass": MASS_BINS,
            }
        else:
            self.legacy_3d = False
            feats = feature_descriptors or ("lift_ratio", "cost_of_transport")
            self.feature_descriptors = tuple(feats[:2])
            self.grid_shape = grid_shape[:2] if len(grid_shape) >= 2 else (16, 16)
            default_ranges: dict[str, tuple[float, float]] = {
                "lift_ratio": (0.15, 0.65),
                "cost_of_transport": (0.01, 0.35),
                "stability_margin": (-0.1, 0.4),
                "stride": (0.05, 0.45),
                "mass": (0.30, 1.50),
            }
            if feature_ranges:
                default_ranges.update(feature_ranges)
            self.feature_ranges = default_ranges
            self.bin_edges = {}
            for i, name in enumerate(self.feature_descriptors):
                r_lo, r_hi = self.feature_ranges.get(name, (0.0, 1.0))
                bins = self.grid_shape[i]
                self.bin_edges[name] = np.linspace(r_lo, r_hi, bins + 1)

    def _clip(self, g: list[float]) -> list[float]:
        return [min(h, max(l, v)) for v, l, h in zip(g, self.lo, self.hi)]

    def _random_genome(self) -> list[float]:
        return [self.rng.uniform(l, h) for l, h in zip(self.lo, self.hi)]

    def propose(self) -> tuple[list[float], int, tuple[int, ...] | None]:
        """Propose a candidate genome using Iso+LineDD crossover or uniform sampling."""
        if not self.archive or self.rng.random() < 0.05:
            legs = self.rng.choice(LEGS) if self.legacy_3d else self.base.get("walker", {}).get("legs", 6)
            return self._random_genome(), legs, None

        elites = list(self.archive.values())
        p1 = self.rng.choice(elites)
        if len(elites) >= 2 and self.rng.random() < 0.7:
            p2 = self.rng.choice(elites)
            while p2 is p1 and len(elites) > 1:
                p2 = self.rng.choice(elites)
            g = self.crossover.propose(p1.genome, p2.genome, bounds=self.bounds)
        else:
            # Local isotropic mutation
            g = [
                min(h, max(l, v * (1 + self.sigma * self.rng.gauss(0, 1)))) if self.rng.random() < 0.4 else v
                for v, l, h in zip(p1.genome, self.lo, self.hi)
            ]

        legs = p1.legs
        if self.legacy_3d and self.rng.random() < 0.15:
            legs = min(LEGS[-1], max(LEGS[0], legs + self.rng.choice([-2, 2])))

        return self._clip(g), legs, p1.cell

    def consider(
        self,
        genome: list[float],
        legs: int | None = None,
        parent: tuple[int, ...] | None = None,
    ) -> bool:
        """Evaluate a proposal; if feasible and it outperforms the current cell elite, insert/replace it."""
        self.evals += 1
        n_legs = legs if legs is not None else self.base.get("walker", {}).get("legs", 6)

        f = self.fit(genome)
        if f <= 0.0:  # Only feasible walking gaits enter the archive; ensures QD-score monotonicity
            return False

        if self.legacy_3d:
            desc = describe(self.base, self.space, genome, n_legs)
            if desc is None:
                return False
            stride, mass = desc
            sb = _bin(stride, self.bin_edges["stride"])
            mb = _bin(mass, self.bin_edges["mass"])
            if sb is None or mb is None:
                return False
            cell = (LEGS.index(n_legs), sb, mb)
            feats = {"stride_m": stride, "mass_kg": mass}
        else:
            feats_desc = describe_features(self.base, self.space, genome, n_legs, self.feature_descriptors)
            if feats_desc is None:
                return False
            coords: list[int] = []
            for name in self.feature_descriptors:
                val = feats_desc.get(name, 0.0)
                b = _bin(val, self.bin_edges[name])
                if b is None:
                    return False
                coords.append(b)
            cell = tuple(coords)
            stride, mass = feats_desc["stride_m"], feats_desc["mass_kg"]
            feats = feats_desc

        cur = self.archive.get(cell)
        if cur is None or f > cur.fitness:
            self.archive[cell] = Elite(
                cell=cell,
                fitness=float(f),
                genome=list(genome),
                legs=n_legs,
                stride_m=float(stride),
                mass_kg=float(mass),
                parent=parent,
                born=self.evals,
                features=feats,
            )
            return True
        return False

    def run(
        self,
        evals: int,
        log_every: int = 100,
        on_progress: Callable[[int, int, float], None] | None = None,
    ) -> None:
        """Run MAP-Elites evolution for a specified number of evaluations."""
        for _ in range(evals):
            self.consider(*self.propose())
            if self.evals % log_every == 0:
                qd = self.qd_score
                self.curve.append((self.evals, len(self.archive), qd))
                if on_progress:
                    on_progress(self.evals, len(self.archive), qd)

    @property
    def cells_total(self) -> int:
        total = 1
        for dim in self.grid_shape:
            total *= dim
        return total

    @property
    def coverage(self) -> float:
        return len(self.archive) / max(1, self.cells_total)

    @property
    def qd_score(self) -> float:
        """QD-score: sum of fitness across all filled archive cells."""
        return float(sum(e.fitness for e in self.archive.values()))

    @property
    def best_fitness(self) -> float:
        return float(max((e.fitness for e in self.archive.values()), default=float("-inf")))

    def pareto_front(
        self,
        objectives: Sequence[tuple[str, str]] | None = None,
    ) -> list[Elite]:
        """Extract non-dominated Pareto front elites across specified objectives.

        Default objectives:
          - fitness (maximize)
          - lift_ratio (maximize)
          - cost_of_transport (minimize)
        """
        if not self.archive:
            return []

        if objectives is None:
            if self.legacy_3d:
                objs = [("fitness", "max"), ("stride_m", "max"), ("mass_kg", "min")]
            else:
                objs = [("fitness", "max"), ("lift_ratio", "max"), ("cost_of_transport", "min")]
        else:
            objs = list(objectives)

        def get_val(e: Elite, key: str) -> float:
            if key == "fitness":
                return e.fitness
            if key in ("stride_m", "stride"):
                return e.stride_m
            if key in ("mass_kg", "mass"):
                return e.mass_kg
            return e.features.get(key, 0.0)

        elites = list(self.archive.values())
        pareto: list[Elite] = []

        for cand in elites:
            cand_vals = [get_val(cand, k) * (1.0 if d == "max" else -1.0) for k, d in objs]
            dominated = False
            for other in elites:
                if other is cand:
                    continue
                other_vals = [get_val(other, k) * (1.0 if d == "max" else -1.0) for k, d in objs]
                all_ge = all(ov >= cv for ov, cv in zip(other_vals, cand_vals))
                any_gt = any(ov > cv for ov, cv in zip(other_vals, cand_vals))
                if all_ge and any_gt:
                    dominated = True
                    break
            if not dominated:
                pareto.append(cand)

        return pareto

    def design_of(self, e: Elite, name: str | None = None) -> dict[str, Any]:
        """The elite as a full design document (an asset derived from base_design)."""
        doc = copy.deepcopy(self.base)
        doc["linkage"] = self.space.to_dict(e.genome)
        doc["walker"]["legs"] = e.legs
        doc["id"] = new_ulid()
        doc["parent"] = {"id": self.base["id"]}
        tag = (
            f"qd-{e.legs}legs-stride{e.stride_m * 100:.0f}cm"
            if self.legacy_3d
            else f"qd-lift{e.lift_ratio:.2f}-cot{e.cost_of_transport:.2f}"
        )
        doc["name"] = name or tag
        doc["notes"] = f"MAP-Elites cell {e.cell}: fitness {e.fitness:.3f}, found at evaluation {e.born}."
        Design(doc)  # validates against design schema
        return doc

    def to_atlas(self) -> dict[str, Any]:
        """Export species atlas as a schema-compliant JSON document."""
        cells_data = []
        for e in self.archive.values():
            entry: dict[str, Any] = {
                "cell": list(e.cell),
                "fitness": float(e.fitness),
                "lift_ratio": float(e.lift_ratio),
                "cost_of_transport": float(e.cost_of_transport),
                "features": {k: float(v) for k, v in e.features.items()},
                "genome": [float(x) for x in e.genome],
                "legs": int(e.legs),
                "stride_m": float(e.stride_m),
                "mass_kg": float(e.mass_kg),
                "born": int(e.born),
                "parent": list(e.parent) if e.parent else None,
                "design": self.design_of(e),
            }
            cells_data.append(entry)

        labels = {
            "lift_ratio": "Obstacle Lift Ratio (z_lift / L)",
            "cost_of_transport": "Cost of Transport (E_transport)",
            "stability_margin": "Dynamic Stability Margin",
            "stride": "Kinematic Stride (m)",
            "mass": "Total Mass (kg)",
            "legs": "Leg Count",
        }

        ranges_export = {}
        for k in self.feature_descriptors:
            if k in self.bin_edges:
                edges = self.bin_edges[k]
                ranges_export[k] = [float(edges[0]), float(edges[-1])]

        front_cells = [list(e.cell) for e in self.pareto_front()]

        atlas = {
            "schema_version": 2,
            "kind": "species_atlas",
            "id": new_ulid(),
            "name": f"Species Atlas ({' x '.join(self.feature_descriptors)})",
            "created": _now_iso(),
            "base_design_id": self.base["id"],
            "dimensions": len(self.feature_descriptors),
            "features": list(self.feature_descriptors),
            "feature_labels": [labels.get(f, f) for f in self.feature_descriptors],
            "feature_ranges": ranges_export,
            "grid_shape": list(self.grid_shape),
            "cells_total": int(self.cells_total),
            "cells_filled": int(len(self.archive)),
            "coverage": float(self.coverage),
            "qd_score": float(self.qd_score),
            "best_fitness": float(self.best_fitness) if self.archive else 0.0,
            "evals": int(self.evals),
            "pareto_front": front_cells,
            "curve": [{"evals": int(c[0]), "cells": int(c[1]), "qd_score": float(c[2])} for c in self.curve],
            "cells": cells_data,
        }
        validate("atlas", atlas)
        return atlas

    def export_atlas(self, path: str | Path) -> dict[str, Any]:
        """Write species atlas JSON document to file."""
        atlas = self.to_atlas()
        Path(path).write_text(json.dumps(atlas, indent=2))
        return atlas

    def export(self, path: str) -> None:
        """Legacy export format for backwards compatibility."""
        rows = [
            {
                "cell": list(e.cell),
                "legs": e.legs,
                "stride_m": e.stride_m,
                "mass_kg": e.mass_kg,
                "fitness": e.fitness,
                "born": e.born,
                "parent": list(e.parent) if e.parent else None,
                "genome": e.genome,
                "lift_ratio": e.lift_ratio,
                "cost_of_transport": e.cost_of_transport,
            }
            for e in self.archive.values()
        ]
        Path(path).write_text(
            json.dumps({"curve": self.curve, "coverage": self.coverage, "cells": rows}, indent=1)
        )


def random_search(base: dict[str, Any], evals: int, seed: int = 0) -> MapElites:
    """Control: uniform random search over the same space."""
    me = MapElites(base, seed=seed)
    for _ in range(evals):
        me.consider(me._random_genome(), me.rng.choice(LEGS) if me.legacy_3d else None, None)
        if me.evals % 100 == 0:
            me.curve.append((me.evals, len(me.archive), me.qd_score))
    return me
