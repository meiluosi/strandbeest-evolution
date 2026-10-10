"""The Python fitness port agrees with the TypeScript reference (contracts/fitness/cases.json)."""
import json
from pathlib import Path

import pytest
from strandbeest_opt.fitness import fitness_flat_stroke, fitness_high_step, infeasibility
from strandbeest_opt.space import GenomeSpace

DATA = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "fitness" / "cases.json").read_text())
SPACES = {k: GenomeSpace.of(v) for k, v in DATA["specs"].items()}


@pytest.mark.parametrize("i", range(len(DATA["cases"])))
def test_python_equals_typescript(i):
    c = DATA["cases"][i]
    space = SPACES[c["spec"]]
    assert fitness_flat_stroke(space)(c["genome"]) == pytest.approx(c["flat"], abs=1e-9)
    assert fitness_high_step(space)(c["genome"]) == pytest.approx(c["highstep"], abs=1e-9)
    inf = infeasibility(space, c["genome"])
    assert (inf is None) == (c["infeasibility"] is None)
    if inf is not None:
        assert inf == pytest.approx(c["infeasibility"], abs=1e-9)


def test_the_corpus_has_feasible_and_infeasible_legs():
    kinds = {c["infeasibility"] is None for c in DATA["cases"]}
    assert kinds == {True, False}
