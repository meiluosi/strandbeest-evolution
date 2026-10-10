"""Quality-diversity: a MAP-Elites archive over walker designs (O-02).

Instead of one best design it keeps the best design in every cell of a grid of descriptors, so you see what the design space
offers: how good can a 4-leg walker with a long stride be, how good a light 12-leg one. Descriptors (all cheap, all from the
kinematics and the bill of materials, so thousands of evaluations are possible without the simulator):
  legs         number of legs (a discrete gene, 4..12 even)
  stride       kinematic stride per crank revolution, m (stroke / duty x unit)
  mass         total mass, kg (frame + motor + bars of all legs)
Objective: the kinematic flat-stroke fitness (higher is better; infeasible legs never enter the archive).
Not included: the start wind of the quasi-static dynamics model (it lives only in TypeScript)."""

from __future__ import annotations

import copy
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from strandbeest_common import Design
from strandbeest_common.gait import gait_metrics
from strandbeest_common.ids import new_ulid

from .fitness import fitness_flat_stroke, infeasibility
from .space import GenomeSpace

LEGS = (4, 6, 8, 10, 12)
STRIDE_BINS = np.linspace(0.05, 0.45, 9)  # m per revolution: 8 bins
MASS_BINS = np.linspace(0.30, 1.50, 7)  # kg: 6 bins


@dataclass
class Elite:
    cell: tuple[int, int, int]
    fitness: float
    genome: list[float]
    legs: int
    stride_m: float
    mass_kg: float
    parent: tuple[int, int, int] | None
    born: int  # evaluation index at which it entered the archive


def _bin(v: float, edges: np.ndarray) -> int | None:
    if v < edges[0] or v >= edges[-1]:
        return None
    return int(np.searchsorted(edges, v, side="right") - 1)


def describe(base: dict[str, Any], space: GenomeSpace, genome: list[float], legs: int) -> tuple[float, float] | None:
    """(stride per revolution in m, total mass in kg) of the design with these lengths and leg count; None if the leg is infeasible."""
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


class MapElites:
    def __init__(self, base_design: dict[str, Any], seed: int = 0, sigma: float = 0.06, lo: float = 0.7, hi: float = 1.4) -> None:
        self.base = copy.deepcopy(base_design)
        self.space = GenomeSpace.of(base_design["linkage"])
        self.fit = fitness_flat_stroke(self.space)
        self.rng = random.Random(seed)
        self.sigma = sigma
        g0 = self.space.to_genome()
        self.lo = [lo * v for v in g0]
        self.hi = [hi * v for v in g0]
        self.archive: dict[tuple[int, int, int], Elite] = {}
        self.evals = 0
        self.curve: list[tuple[int, int, float]] = []  # (evaluations, cells filled, QD score = sum of fitness)

    def _clip(self, g: list[float]) -> list[float]:
        return [min(h, max(l, v)) for v, l, h in zip(g, self.lo, self.hi)]

    def _random_genome(self) -> list[float]:
        return [self.rng.uniform(l, h) for l, h in zip(self.lo, self.hi)]

    def propose(self) -> tuple[list[float], int, tuple[int, int, int] | None]:
        if not self.archive or self.rng.random() < 0.05:
            return self._random_genome(), self.rng.choice(LEGS), None
        parent = self.rng.choice(list(self.archive.values()))
        g = [v * (1 + self.sigma * self.rng.gauss(0, 1)) if self.rng.random() < 0.4 else v for v in parent.genome]
        legs = parent.legs
        if self.rng.random() < 0.15:
            legs = min(LEGS[-1], max(LEGS[0], legs + self.rng.choice([-2, 2])))
        return self._clip(g), legs, parent.cell

    def consider(self, genome: list[float], legs: int, parent: tuple[int, int, int] | None) -> bool:
        self.evals += 1
        f = self.fit(genome)
        if f <= -4:
            return False
        desc = describe(self.base, self.space, genome, legs)
        if desc is None:
            return False
        stride, mass = desc
        sb, mb = _bin(stride, STRIDE_BINS), _bin(mass, MASS_BINS)
        if sb is None or mb is None:
            return False
        cell = (LEGS.index(legs), sb, mb)
        cur = self.archive.get(cell)
        if cur is None or f > cur.fitness:
            self.archive[cell] = Elite(cell, f, genome, legs, stride, mass, parent, self.evals)
            return True
        return False

    def run(self, evals: int, log_every: int = 100) -> None:
        for _ in range(evals):
            self.consider(*self.propose())
            if self.evals % log_every == 0:
                self.curve.append((self.evals, len(self.archive), float(sum(e.fitness for e in self.archive.values()))))

    @property
    def cells_total(self) -> int:
        return len(LEGS) * (len(STRIDE_BINS) - 1) * (len(MASS_BINS) - 1)

    @property
    def coverage(self) -> float:
        return len(self.archive) / self.cells_total

    def design_of(self, e: Elite, name: str | None = None) -> dict[str, Any]:
        """The elite as a full design document (a new asset whose parent is the base design); opens in the designer as is."""
        doc = copy.deepcopy(self.base)
        doc["linkage"] = self.space.to_dict(e.genome)
        doc["walker"]["legs"] = e.legs
        doc["id"] = new_ulid()
        doc["parent"] = {"id": self.base["id"]}
        doc["name"] = name or f"qd-{e.legs}legs-stride{e.stride_m * 100:.0f}cm-mass{e.mass_kg * 1000:.0f}g"
        doc["notes"] = f"MAP-Elites cell {e.cell}: flat-stroke fitness {e.fitness:.3f}, found at evaluation {e.born}."
        Design(doc)  # validates
        return doc

    def export(self, path: str) -> None:
        rows = [{"cell": list(e.cell), "legs": e.legs, "stride_m": e.stride_m, "mass_kg": e.mass_kg, "fitness": e.fitness, "born": e.born, "parent": list(e.parent) if e.parent else None, "genome": e.genome} for e in self.archive.values()]
        open(path, "w").write(json.dumps({"curve": self.curve, "coverage": self.coverage, "cells": rows}, indent=1))


def random_search(base: dict[str, Any], evals: int, seed: int = 0) -> MapElites:
    """Control: the same archive filled by sampling designs uniformly (no selection from the archive)."""
    me = MapElites(base, seed)
    for i in range(evals):
        me.consider(me._random_genome(), me.rng.choice(LEGS), None)
        if me.evals % 100 == 0:
            me.curve.append((me.evals, len(me.archive), float(sum(e.fitness for e in me.archive.values()))))
    return me
