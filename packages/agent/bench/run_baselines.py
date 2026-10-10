"""Run every baseline agent on every task (2 seeds) and write bench/baselines.json. Slow: each run simulates the visible scene
a few times and the blind scenes once. Regenerate when tasks, scenes or the simulator change."""
import json
import tempfile
from pathlib import Path

from strandbeest_agent.bench import BASELINES, BENCH, load_tasks, run_agent

out = {"_doc": "Baseline scores of bench/tasks.json (relative improvement of the blind metric over the starting design; 0 = no gain or disqualified). Same tools and budget as any agent.", "results": []}
for task in load_tasks()["tasks"]:
    for name, agent in BASELINES.items():
        for seed in (1, 2):
            with tempfile.TemporaryDirectory() as tmp:
                s, spent = run_agent(task, agent, Path(tmp) / "ws", seed)
            row = {"task": task["id"], "agent": name, "seed": seed, "score": s.score, "reason": s.reason, "value": s.value, "start_value": s.start_value, **spent}
            out["results"].append(row)
            print(row, flush=True)
(BENCH / "baselines.json").write_text(json.dumps(out, indent=1) + "\n")
