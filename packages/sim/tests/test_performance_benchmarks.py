"""H5-02 Performance budgets and regression test suite.

Ensures that:
1. Canonical 6-leg walker step latency remains within 0.30 ms/step.
2. 12-leg walker step latency remains within 0.60 ms/step.
3. 3-walker beach herd step latency remains within 1.00 ms/step.
4. Continuous simulation memory growth remains bounded (< 5 MiB over multi-run steps).
"""

import copy
import gc
import resource
import time

import pytest
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run_herd, scenario_from_design


@pytest.fixture(scope="module")
def small_6leg_scenario():
    design = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
    sc = scenario_from_design(design)
    return sc.model_dump(mode="json")


def test_performance_6leg_walker_latency_budget(small_6leg_scenario):
    """Verify 6-leg canonical walker steps within budget (<= 0.30 ms/step)."""
    # 0.4s @ 0.2ms = 2000 steps
    _ = run_herd(small_6leg_scenario, duration=0.05)  # Warmup
    gc.collect()

    t0 = time.perf_counter()
    res = run_herd(small_6leg_scenario, duration=0.4)
    t1 = time.perf_counter()

    n_steps = len(res.walkers["walker"].t)
    assert n_steps >= 1000
    step_ms = ((t1 - t0) / n_steps) * 1000.0

    # Strict budget assertion (0.30 ms/step)
    assert step_ms <= 0.30, f"6-leg step latency {step_ms:.4f} ms exceeded budget 0.30 ms"


def test_performance_12leg_walker_latency_budget(small_6leg_scenario):
    """Verify 12-leg walker steps within budget (<= 0.60 ms/step)."""
    sc12 = copy.deepcopy(small_6leg_scenario)
    sc12["entities"][0]["components"]["body"]["legs"] = 12

    _ = run_herd(sc12, duration=0.05)  # Warmup
    gc.collect()

    t0 = time.perf_counter()
    res = run_herd(sc12, duration=0.4)
    t1 = time.perf_counter()

    n_steps = len(res.walkers["walker"].t)
    assert n_steps >= 1000
    step_ms = ((t1 - t0) / n_steps) * 1000.0

    # Strict budget assertion (0.60 ms/step)
    assert step_ms <= 0.60, f"12-leg step latency {step_ms:.4f} ms exceeded budget 0.60 ms"


def test_performance_3walker_herd_latency_budget(small_6leg_scenario):
    """Verify 3-walker herd steps within budget (<= 1.00 ms/step)."""
    ent_template = small_6leg_scenario["entities"][0]
    walker_configs = [
        {"name": "leader", "x": 0.0, "y": 0.0},
        {"name": "left", "x": 1.0, "y": 1.0},
        {"name": "right", "x": -1.0, "y": -1.0},
    ]
    entities = []
    for c in walker_configs:
        ent = copy.deepcopy(ent_template)
        ent["name"] = c["name"]
        ent["placement"] = {"x": c["x"], "y": c["y"], "phase_offset": 0.0}
        entities.append(ent)

    doc = {
        "schema_version": 2,
        "name": "beach-herd-3",
        "world": small_6leg_scenario["world"],
        "entities": entities,
        "solver": small_6leg_scenario["solver"],
    }

    _ = run_herd(doc, duration=0.05)  # Warmup
    gc.collect()

    t0 = time.perf_counter()
    res = run_herd(doc, duration=0.4)
    t1 = time.perf_counter()

    n_steps = len(res.walkers["leader"].t)
    assert n_steps >= 1000
    step_ms = ((t1 - t0) / n_steps) * 1000.0

    # Strict budget assertion (1.00 ms/step)
    assert step_ms <= 1.00, f"3-walker herd step latency {step_ms:.4f} ms exceeded budget 1.00 ms"


def test_performance_memory_leak_budget(small_6leg_scenario):
    """Verify simulation process resident memory does not grow unboundedly."""
    gc.collect()
    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    total_steps = 0
    for _ in range(3):
        res = run_herd(small_6leg_scenario, duration=0.3)
        total_steps += len(res.walkers["walker"].t)
        del res
        gc.collect()

    rss_end = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    growth_mib = max(0, rss_end - rss_start) / (1024 * 1024)

    # Budget: memory growth over runs < 5.0 MiB
    assert growth_mib <= 5.0, f"Memory growth {growth_mib:.2f} MiB exceeded budget 5.0 MiB"
