"""Run every baseline agent on every task and write bench/baselines.json. Slow: each run simulates the visible scene a few times
and the blind scenes once. Regenerate when tasks, scenes or the simulator change.

Usage: python bench/run_baselines.py [seeds=10] [workers=4]

Runs are independent and the budget is counted in simulations and operations, never in seconds, so they run in parallel without
changing any score. The previous baselines.json is kept as `previous` in the new file so old and new values stay side by side.
"""
import json
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from strandbeest_agent.bench import BASELINES, BENCH, load_tasks, run_agent

DOC = "Baseline scores of bench/tasks.json (relative improvement of the blind metric over the starting design; 0 = no gain or disqualified). Same tools and budget as any agent."


def one(job: tuple[str, str, int]) -> dict:
    task_id, name, seed = job
    task = next(t for t in load_tasks()["tasks"] if t["id"] == task_id)
    with tempfile.TemporaryDirectory() as tmp:
        s, spent = run_agent(task, BASELINES[name], Path(tmp) / "ws", seed)
    row = {"task": task_id, "agent": name, "seed": seed, "score": s.score, "reason": s.reason, "value": s.value, "start_value": s.start_value, **spent}
    print(row, flush=True)
    return row


def main() -> None:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    path = BENCH / "baselines.json"
    previous = json.loads(path.read_text())["results"] if path.exists() else []
    jobs = [(t["id"], name, seed) for t in load_tasks()["tasks"] for name in BASELINES for seed in range(1, n_seeds + 1)]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(one, jobs))
    out = {"_doc": DOC, "seeds": n_seeds, "results": rows, "previous": previous}
    path.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
