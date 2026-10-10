"""The search space of an optimiser over one linkage topology: a genome is the list of its named lengths. Python twin of
packages/core/src/genome.ts (the optimiser objectives are corpus-checked against the TypeScript ones: contracts/fitness)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from strandbeest_common.linkage import LinkageSpec, load_spec


@dataclass(frozen=True)
class GenomeSpace:
    base: dict[str, Any]  # a LinkageSpec as a dict
    names: tuple[str, ...]

    @classmethod
    def of(cls, spec: dict[str, Any]) -> "GenomeSpace":
        return cls(copy.deepcopy(spec), tuple(spec["params"]))

    def to_dict(self, genome) -> dict[str, Any]:
        if len(genome) != len(self.names):
            raise ValueError(f"genome has {len(genome)} values, expected {len(self.names)}")
        d = copy.deepcopy(self.base)
        d["params"] = {n: float(v) for n, v in zip(self.names, genome)}
        return d

    def to_spec(self, genome) -> LinkageSpec:
        return load_spec(self.to_dict(genome))

    def to_genome(self, spec: dict[str, Any] | None = None) -> list[float]:
        spec = spec or self.base
        return [float(spec["params"][n]) for n in self.names]
