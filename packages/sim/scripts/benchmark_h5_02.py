#!/usr/bin/env python3
"""H5-02 Performance & Maintainability Benchmark Suite.

Measures:
1. Simulation latency (ms/step) & Real-Time Factor (RTF) across 6-leg, 12-leg, and 3-walker herd scenarios.
2. Memory consumption (peak resident set size & leak rate over 5,000 steps).
3. Asset budgets and regression thresholds.

Usage:
    .venv/bin/python packages/sim/scripts/benchmark_h5_02.py [--save]
"""

import copy
import gc
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

import mujoco
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run_herd, scenario_from_design

# Performance budgets and regression alert thresholds (+20% tolerance over budget)
BUDGETS = {
    "walker_6leg": {
        "max_step_ms": 0.30,  # Alert threshold if > 0.30 ms
        "min_rtf": 0.50,       # At dt=0.2ms, rtf > 0.5x
    },
    "walker_12leg": {
        "max_step_ms": 0.60,  # Alert threshold if > 0.60 ms
        "min_rtf": 0.30,
    },
    "herd_3walkers": {
        "max_step_ms": 1.00,  # Alert threshold if > 1.00 ms
        "min_rtf": 0.20,
    },
    "memory": {
        "max_leak_rate_kib_per_step": 0.20,  # < 0.2 KiB/step
        "max_growth_mib_5000_steps": 5.0,    # < 5.0 MiB over 5000 steps
    },
}


def get_platform_info() -> dict[str, str]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "mujoco_version": mujoco.__version__,
    }


def benchmark_6leg(n_steps_warmup: int = 200, duration: float = 1.0) -> dict[str, float]:
    design = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
    sc = scenario_from_design(design)
    doc = sc.model_dump(mode="json")

    # Warmup
    _ = run_herd(doc, duration=0.1)
    gc.collect()

    t0 = time.perf_counter()
    res = run_herd(doc, duration=duration)
    t1 = time.perf_counter()

    n_steps = len(res.walkers["walker"].t)
    dt = res.walkers["walker"].t[1] - res.walkers["walker"].t[0]
    elapsed_s = t1 - t0
    step_ms = (elapsed_s / n_steps) * 1000.0
    rtf = duration / elapsed_s

    return {
        "duration_s": duration,
        "n_steps": n_steps,
        "timestep_s": dt,
        "elapsed_s": elapsed_s,
        "step_ms": step_ms,
        "rtf": rtf,
    }


def benchmark_12leg(n_steps_warmup: int = 200, duration: float = 1.0) -> dict[str, float]:
    design = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
    sc = scenario_from_design(design)
    doc = sc.model_dump(mode="json")
    doc["entities"][0]["components"]["body"]["legs"] = 12

    # Warmup
    _ = run_herd(doc, duration=0.1)
    gc.collect()

    t0 = time.perf_counter()
    res = run_herd(doc, duration=duration)
    t1 = time.perf_counter()

    n_steps = len(res.walkers["walker"].t)
    dt = res.walkers["walker"].t[1] - res.walkers["walker"].t[0]
    elapsed_s = t1 - t0
    step_ms = (elapsed_s / n_steps) * 1000.0
    rtf = duration / elapsed_s

    return {
        "duration_s": duration,
        "n_steps": n_steps,
        "timestep_s": dt,
        "elapsed_s": elapsed_s,
        "step_ms": step_ms,
        "rtf": rtf,
    }


def benchmark_3walker_herd(duration: float = 1.0) -> dict[str, float]:
    design = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
    sc = scenario_from_design(design)
    ent_template = sc.entities[0].model_dump(mode="json")

    walker_configs = [
        {"name": "leader", "x": 0.0, "y": 0.0},
        {"name": "flanker_left", "x": 1.0, "y": 1.5},
        {"name": "flanker_right", "x": -1.0, "y": -1.5},
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
        "world": sc.world.model_dump(mode="json"),
        "entities": entities,
        "solver": sc.solver.model_dump(mode="json"),
    }

    # Warmup
    _ = run_herd(doc, duration=0.1)
    gc.collect()

    t0 = time.perf_counter()
    res = run_herd(doc, duration=duration)
    t1 = time.perf_counter()

    n_steps = len(res.walkers["leader"].t)
    dt = res.walkers["leader"].t[1] - res.walkers["leader"].t[0]
    elapsed_s = t1 - t0
    step_ms = (elapsed_s / n_steps) * 1000.0
    rtf = duration / elapsed_s

    return {
        "duration_s": duration,
        "n_steps": n_steps,
        "timestep_s": dt,
        "elapsed_s": elapsed_s,
        "step_ms": step_ms,
        "rtf": rtf,
    }


def benchmark_memory_drift(n_runs: int = 3, duration_per_run: float = 1.0) -> dict[str, float]:
    design = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
    sc = scenario_from_design(design)
    doc = sc.model_dump(mode="json")

    gc.collect()
    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    total_steps = 0

    for _ in range(n_runs):
        res = run_herd(doc, duration=duration_per_run)
        total_steps += len(res.walkers["walker"].t)
        del res
        gc.collect()

    rss_end = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_growth_bytes = max(0, rss_end - rss_start)
    growth_mib = rss_growth_bytes / (1024 * 1024)
    leak_rate_kib = (rss_growth_bytes / 1024) / total_steps if total_steps > 0 else 0.0

    return {
        "n_runs": n_runs,
        "total_steps": total_steps,
        "rss_start_mib": rss_start / (1024 * 1024),
        "rss_end_mib": rss_end / (1024 * 1024),
        "growth_mib": growth_mib,
        "leak_rate_kib_per_step": leak_rate_kib,
    }


def run_all_benchmarks() -> dict:
    platform_info = get_platform_info()

    bench_6leg = benchmark_6leg()
    bench_12leg = benchmark_12leg()
    bench_herd = benchmark_3walker_herd()
    bench_mem = benchmark_memory_drift()

    # Regression compliance check
    checks = {
        "6leg_within_budget": bench_6leg["step_ms"] <= BUDGETS["walker_6leg"]["max_step_ms"],
        "12leg_within_budget": bench_12leg["step_ms"] <= BUDGETS["walker_12leg"]["max_step_ms"],
        "herd_within_budget": bench_herd["step_ms"] <= BUDGETS["herd_3walkers"]["max_step_ms"],
        "memory_within_budget": bench_mem["growth_mib"] <= BUDGETS["memory"]["max_growth_mib_5000_steps"],
    }
    all_passed = all(checks.values())

    report = {
        "platform": platform_info,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "budgets": BUDGETS,
        "results": {
            "walker_6leg": bench_6leg,
            "walker_12leg": bench_12leg,
            "herd_3walkers": bench_herd,
            "memory": bench_mem,
        },
        "checks": checks,
        "passed": all_passed,
    }
    return report


def main() -> None:
    report = run_all_benchmarks()
    out = json.dumps(report, indent=2)
    print(out)

    if "--save" in sys.argv:
        repo_root = Path(__file__).resolve().parents[3]
        dest = repo_root / "experiments" / "benchmark-h5-02-performance.json"
        dest.write_text(out + "\n")
        print(f"\n[Saved to {dest}]")

    if not report["passed"]:
        print("\nERROR: Performance degradation exceeded budget thresholds!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
