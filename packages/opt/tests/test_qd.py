"""O-02: the MAP-Elites archive."""
import json
from pathlib import Path

import pytest
from strandbeest_common import Design
from strandbeest_opt.qd import LEGS, MapElites, describe, random_search

BASE = json.loads((Path(__file__).resolve().parents[3] / "schemas" / "examples" / "design-jansen-small-6leg.json").read_text())


def test_describe_gives_stride_and_mass_of_jansens_leg():
    me = MapElites(BASE)
    stride, mass = describe(BASE, me.space, me.space.to_genome(), 6)
    assert 0.2 < stride < 0.4  # the small walker's kinematic stride is about 0.28 m
    assert 0.35 < mass < 1.0
    more = describe(BASE, me.space, me.space.to_genome(), 12)[1]
    assert more > mass  # more legs, more bars


def test_the_archive_fills_keeps_the_best_per_cell_and_every_elite_opens_as_a_valid_design():
    me = MapElites(BASE, seed=3)
    me.run(1500)
    assert len(me.archive) > 15 and all(e.fitness > -4 for e in me.archive.values())
    for e in list(me.archive.values())[:5]:
        d = me.design_of(e)
        Design(d)
        assert d["parent"]["id"] == BASE["id"] and d["walker"]["legs"] == e.legs
    # per cell only the best seen is kept: re-considering a worse genome with the same descriptors changes nothing
    e = next(iter(me.archive.values()))
    before = dict(me.archive)
    assert me.consider(e.genome, e.legs, None) is False and me.archive == before
    qd = [c[2] for c in me.curve]
    assert qd == sorted(qd) and me.curve[-1][1] == len(me.archive)  # the QD score never decreases


def test_selection_from_the_archive_beats_uniform_sampling_for_the_same_evaluations():
    qd = MapElites(BASE, seed=1)
    qd.run(2500)
    rs = random_search(BASE, 2500, seed=1)
    assert len(qd.archive) > len(rs.archive)
    assert sum(e.fitness for e in qd.archive.values()) > sum(e.fitness for e in rs.archive.values())
