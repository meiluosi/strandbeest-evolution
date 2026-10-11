"""The agent design benchmark (A-04): tasks, blind scoring, baselines.

An agent works through the tool surface (registry.py) with the task's budget and may only simulate the task's visible scenes.
When it is done its design is scored on blind scenes it could not see:
  invalid design (guard error), outside the allowed envelope, or a blind run the simulator skeptic distrusts  -> score 0
  otherwise  score = relative improvement of the blind metric over the starting design (positive = better; capped at +2).
The starting design scores 0 by construction. Baselines (random edits, hill climbing, CMA-ES on a kinematic proxy) use the same
tools and budget; their scores are in bench/baselines.json and are the numbers an agent has to beat."""

from __future__ import annotations

import json
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
from strandbeest_common import Design
from strandbeest_common.guard import default_problems
from strandbeest_common.schemas import schema_dir
from strandbeest_fab import printable_problems

from .registry import Budget, Registry, Session
from .tools import default_registry
from .workspace import ToolError, Workspace

BENCH = Path(__file__).resolve().parents[2] / "bench"
ALLOWED_SCENES_KEY = "visible_scenes"
CAP = 2.0


def load_tasks() -> dict[str, Any]:
    return json.loads((BENCH / "tasks.json").read_text())


def _blind() -> dict[str, Any]:
    return json.loads((BENCH / "blind-scenes.json").read_text())["scenes"]


@dataclass
class Score:
    task: str
    score: float
    value: float | None
    start_value: float | None
    reason: str = "ok"
    detail: dict[str, Any] = field(default_factory=dict)


def metric_of(task: dict[str, Any], metrics: dict[str, Any]) -> float | None:
    if task["metric"] == "energy_per_metre":
        e, s = metrics.get("energy_in_per_rev"), metrics.get("stride_per_rev")
        return e / s if e and s and s > 0 else None
    v = metrics.get(task["metric"])
    return v if v is not None and v == v else None


def blind_value(task: dict[str, Any], design: dict[str, Any]) -> tuple[float | None, list[str], dict[str, Any]]:
    """Run the task's blind scenes on `design`; returns (mean metric, distrust reasons, per-scene numbers)."""
    from strandbeest_api.pipeline import simulate
    from strandbeest_sim import sim_config
    from strandbeest_sim.skeptic import audit

    blind = _blind()
    values, reasons, per = [], [], {}
    for name in task["blind"]:
        with tempfile.TemporaryDirectory() as tmp:
            doc = simulate(Design(design), Path(tmp), json.loads(json.dumps(blind[name])))
            arrays = np.load(Path(tmp) / doc["id"] / "arrays.npz")
            findings = audit(sim_config(doc["scenario"]), doc["metrics"], {k: arrays[k] for k in arrays.files}, doc.get("stalled", False))
        v = metric_of(task, doc["metrics"])
        per[name] = {"value": v, "findings": [f.check for f in findings]}
        reasons += [f"{name}: {f.check}" for f in findings]
        if v is None:
            reasons.append(f"{name}: no {task['metric']}")
        else:
            values.append(v)
    return (float(np.mean(values)) if len(values) == len(task["blind"]) else None), reasons, per


def in_envelope(task: dict[str, Any], start: dict[str, Any], design: dict[str, Any]) -> str | None:
    env = task["envelope"]
    if design["walker"]["legs"] != env["legs"]:
        return f"legs must stay {env['legs']}"
    lo, hi = env["length_ratio"]
    for k, v0 in start["linkage"]["params"].items():
        v = design["linkage"]["params"].get(k)
        if v is None:
            return f"length {k} removed"
        if not lo * v0 - 1e-9 <= v <= hi * v0 + 1e-9:
            return f"length {k} = {v:g} is outside [{lo}, {hi}] x the original {v0:g}"
    if len(design["linkage"]["joints"]) != len(start["linkage"]["joints"]):
        return "the topology must stay the same"
    return None


def score(task: dict[str, Any], start: dict[str, Any], design: dict[str, Any], start_value: float | None = None) -> Score:
    out = in_envelope(task, start, design)
    if out:
        return Score(task["id"], 0.0, None, start_value, "outside_envelope", {"why": out})
    problems = [p for p in default_problems(design) + printable_problems(design) if p["level"] == "error"]
    if problems:
        return Score(task["id"], 0.0, None, start_value, "invalid_design", {"problems": [p["code"] for p in problems]})
    if start_value is None:
        start_value, _, _ = blind_value(task, start)
    value, reasons, per = blind_value(task, design)
    if reasons:
        return Score(task["id"], 0.0, value, start_value, "distrusted_run", {"reasons": reasons, "scenes": per})
    assert value is not None and start_value
    gain = (value - start_value) / abs(start_value)
    if task["direction"] == "min":
        gain = -gain
    return Score(task["id"], float(min(CAP, gain)), value, start_value, "ok", {"scenes": per})


# ---- the agent side ------------------------------------------------------------------------------------------------
class ToolClient:
    """What an agent gets: the registry, a session with the task's budget, and a scene whitelist. It cannot reach the blind scenes."""

    def __init__(self, ws: Workspace, task: dict[str, Any], registry: Registry | None = None, actor: str = "bench-agent") -> None:
        self.ws, self.task = ws, task
        self.registry = registry or default_registry()
        b = task["budget"]
        self.session = Session(actor_id=actor, budget=Budget(sim_runs=b["sim_runs"], ops=b["ops"], sim_seconds=float("inf")))  # wall-clock is not part of the benchmark: scores must not depend on the machine

    def call(self, tool: str, **args: Any) -> Any:
        if tool == "simulate.run" and args.get("scene", "flat") not in self.task[ALLOWED_SCENES_KEY]:
            raise ToolError("scene_not_allowed", f"this task allows the scenes {self.task[ALLOWED_SCENES_KEY]}")
        return self.registry.call(self.ws, self.session, tool, args)


Agent = Callable[[ToolClient, str, random.Random], None]


def _value(client: ToolClient, did: str) -> float | None:
    run = client.call("simulate.run", design=did, scene=client.task[ALLOWED_SCENES_KEY][0], revolutions=2.1)
    return metric_of(client.task, run["metrics"])


def _better(task, a, b) -> bool:
    return b is not None and (a is None or (b < a if task["direction"] == "min" else b > a))


def random_edits_agent(client: ToolClient, did: str, rng: random.Random) -> None:
    """Baseline: random bounded edits of one length at a time, keep what improves the visible metric, undo what does not."""
    best = _value(client, did)
    names = list(json.loads(client.ws._doc_path(did).read_text())["linkage"]["params"])
    while client.session.spent_runs < client.session.budget.sim_runs:
        name = rng.choice(names)
        cur = client.call("design.get", design=did)["linkage"]["params"][name]
        try:
            client.call("design.set_param", design=did, name=name, value=cur * rng.uniform(0.9, 1.1), reason="random edit")
        except ToolError:
            continue
        v = _value(client, did)
        if _better(client.task, best, v):
            best = v
        else:
            client.call("design.undo", design=did)


def hill_climb_agent(client: ToolClient, did: str, rng: random.Random) -> None:
    """Baseline: greedy hill climbing on the crank and the longest bars, step 4 % up or down, shrinking when stuck."""
    best = _value(client, did)
    step = 0.06
    names = ["m", "b", "j", "e", "k", "h"]
    i = 0
    while client.session.spent_runs < client.session.budget.sim_runs:
        name = names[i % len(names)]
        i += 1
        cur = client.call("design.get", design=did)["linkage"]["params"][name]
        sign = rng.choice([-1, 1])
        try:
            client.call("design.set_param", design=did, name=name, value=cur * (1 + sign * step), reason="hill climb")
        except ToolError:
            continue
        v = _value(client, did)
        if _better(client.task, best, v):
            best = v
        else:
            client.call("design.undo", design=did)
            if i % len(names) == 0:
                step = max(0.02, step * 0.7)


def cmaes_proxy_agent(client: ToolClient, did: str, rng: random.Random) -> None:
    """Baseline: CMA-ES on the free kinematic flat-stroke fitness (no simulations), applied as one grouped edit, then keep it only
    if the visible simulation does not get worse."""
    from strandbeest_opt import CmaEs, GenomeSpace, fitness_flat_stroke, optimize

    d = client.call("design.get", design=did)
    space = GenomeSpace.of(d["linkage"])
    x0 = space.to_genome()
    lo = [v * 0.75 for v in x0]
    hi = [v * 1.35 for v in x0]
    best, _, _ = optimize(CmaEs(x0, 0.08 * float(np.mean(x0)), (lo, hi), seed=rng.randrange(1000), popsize=24), fitness_flat_stroke(space), 2400)
    before = _value(client, did)
    done = []
    for name, v in zip(space.names, best):
        if abs(v - d["linkage"]["params"][name]) > 1e-9:
            try:
                client.call("design.set_param", design=did, name=name, value=float(v), reason="CMA-ES on the kinematic proxy")
                done.append(name)
            except ToolError:
                pass
    after = _value(client, did)
    if not _better(client.task, before, after):
        for _ in done:
            client.call("design.undo", design=did)


BASELINES: dict[str, Agent] = {"random-edits": random_edits_agent, "hill-climb": hill_climb_agent, "cmaes-proxy": cmaes_proxy_agent}


def run_agent(task: dict[str, Any], agent: Agent, workdir: Path, seed: int = 0) -> tuple[Score, dict[str, Any]]:
    """Give `agent` a fresh copy of the starting design and the task's budget, then score what it leaves."""
    ws = Workspace(workdir)
    start_name = load_tasks()["start_design"]
    client = ToolClient(ws, task)
    did = client.call("design.create", example=start_name, name="work")["design_id"]
    agent(client, did, random.Random(seed))
    final = ws.history(did).design
    start = Design.load(schema_dir() / "examples" / f"design-{start_name}.json").doc
    return score(task, start, final), {"runs": client.session.spent_runs, "ops": client.session.spent_ops}
