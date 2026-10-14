"""W-03: the start-wind search (logic only; the real simulation is injected, see strandbeest_sim.startwind)."""

import math

import pytest

from strandbeest_sim.startwind import find_start_wind


def fake(threshold, valid=True):
    calls = []

    def attempt(w):
        calls.append(w)
        return {"started": w >= threshold, "valid": valid}

    return attempt, calls


@pytest.mark.parametrize("threshold", [0.03, 0.2, 0.45, 0.5, 0.97, 3.3, 17.0])
def test_the_interval_brackets_the_threshold_within_tolerance(threshold):
    attempt, calls = fake(threshold)
    r = find_start_wind(attempt, guess=0.5, rel_tol=0.05)
    assert r.found and r.lo < threshold <= r.hi
    assert r.hi / r.lo <= 1.05 + 1e-12
    assert r.lo <= r.estimate <= r.hi
    assert len(calls) == len(set(calls)) == len(r.runs)  # no wind is simulated twice


def test_the_number_of_simulations_is_logarithmic_in_the_precision():
    attempt, calls = fake(0.45)
    find_start_wind(attempt, guess=0.5, rel_tol=0.05)
    assert len(calls) <= 8  # a bracket of one octave to 5 % takes about log2(ln 2 / ln 1.05) = 4 bisections


def test_a_walker_that_never_starts_gives_an_open_interval():
    attempt, _ = fake(1e9)
    r = find_start_wind(attempt, guess=0.5, w_max=30.0)
    assert not r.found and math.isinf(r.hi) and math.isnan(r.estimate) and "does not start" in r.note
    assert r.lo > 15  # the highest wind tried that did not start


def test_a_walker_that_always_starts_gives_an_interval_open_at_zero():
    attempt, _ = fake(0.0)
    r = find_start_wind(attempt, guess=0.5, w_min=0.02)
    assert not r.found and r.lo == 0.0 and r.hi >= 0.02 and "lowest wind" in r.note


def test_max_runs_stops_the_search_and_says_so():
    attempt, calls = fake(0.45)
    r = find_start_wind(attempt, guess=0.5, rel_tol=1e-9, max_runs=6)
    assert len(calls) == 6 and r.found and "stopped after 6" in r.note and r.lo < 0.45 <= r.hi


def test_a_run_that_broke_the_simulator_makes_the_result_untrusted():
    attempt, _ = fake(0.45, valid=False)
    assert not find_start_wind(attempt).trusted
    attempt, _ = fake(0.45, valid=True)
    assert find_start_wind(attempt).trusted
