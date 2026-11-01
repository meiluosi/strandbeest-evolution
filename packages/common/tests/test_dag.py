"""Tests for DAG job scheduling and asynchronous ask/tell optimization engine (ADR-0004, E5-04)."""

import pytest
import time
from strandbeest_common.dag import AskTellScheduler, JobDAG, JobNode


def test_dag_topological_execution():
    dag = JobDAG()
    order = []

    def task_a():
        order.append("A")
        return 10

    def task_b():
        order.append("B")
        return 20

    def task_c():
        # C depends on A and B
        order.append("C")
        return dag.nodes["A"].result + dag.nodes["B"].result

    dag.add_node("A", task_a, dependencies=(), resources={"cpu": 1})
    dag.add_node("B", task_b, dependencies=(), resources={"cpu": 1})
    dag.add_node("C", task_c, dependencies=["A", "B"], resources={"cpu": 1})

    results = dag.execute(max_workers=2)
    assert results["A"] == 10
    assert results["B"] == 20
    assert results["C"] == 30
    assert order[-1] == "C"  # C must execute after A and B


def test_dag_cycle_detection():
    dag = JobDAG()
    dag.add_node("N1", lambda: 1, dependencies=["N2"])
    dag.add_node("N2", lambda: 2, dependencies=["N1"])

    with pytest.raises(ValueError, match="cycle detected"):
        dag.execute()


def test_dag_missing_dependency():
    dag = JobDAG()
    dag.add_node("N1", lambda: 1, dependencies=["MISSING"])

    with pytest.raises(ValueError, match="non-existent node"):
        dag.execute()


def test_dag_downstream_cancellation_on_failure():
    dag = JobDAG()

    def will_fail():
        raise RuntimeError("boom")

    def should_not_run():
        return 42

    dag.add_node("F", will_fail)
    dag.add_node("D", should_not_run, dependencies=["F"])

    results = dag.execute()
    assert dag.nodes["F"].status == "failed"
    assert dag.nodes["D"].status == "cancelled"
    assert results["D"] is None


class ToyOptimizer:
    """A minimal optimizer following OptimizerProtocol to test AskTellScheduler."""

    def __init__(self, target: float = 7.5, step_size: float = 0.5):
        self.target = target
        self.step_size = step_size
        self.current = 0.0
        self.best = 0.0
        self.best_f = -float("inf")
        self.generation = 0

    def ask(self) -> list[float]:
        # Generate 4 candidates around current
        return [
            self.current - self.step_size,
            self.current,
            self.current + self.step_size,
            self.current + 2 * self.step_size,
        ]

    def tell(self, xs, fs):
        self.generation += 1
        for x, f in zip(xs, fs):
            if f > self.best_f:
                self.best = x
                self.best_f = f
                self.current = x

    def stop(self) -> bool:
        return abs(self.best - self.target) < 0.1 or self.generation >= 25


def test_ask_tell_scheduler_runs_toy_optimizer():
    # Maximize f(x) = -(x - 7.5)^2
    def evaluate(x: float) -> float:
        return -((x - 7.5) ** 2)

    opt = ToyOptimizer(target=7.5, step_size=0.5)
    scheduler = AskTellScheduler(opt, eval_fn=evaluate, max_workers=2, max_evals=100)

    best_x, best_f = scheduler.run_until_stop()

    assert abs(best_x - 7.5) < 0.1
    assert best_f > -0.05
    assert scheduler.total_evals > 0


def test_dag_resource_limits_concurrency():
    """Verify that resource limits prevent over-allocation regardless of max_workers."""
    dag = JobDAG()
    active_gpu_tasks = 0
    max_active_gpu_seen = 0
    lock = time_lock = __import__("threading").Lock()

    def gpu_task(idx: int):
        nonlocal active_gpu_tasks, max_active_gpu_seen
        with lock:
            active_gpu_tasks += 1
            if active_gpu_tasks > max_active_gpu_seen:
                max_active_gpu_seen = active_gpu_tasks
        time.sleep(0.02)
        with lock:
            active_gpu_tasks -= 1
        return idx * 2

    for i in range(5):
        dag.add_node(f"task_{i}", gpu_task, (), {"gpu": 1}, i)

    # max_workers=5 would run all 5 concurrently if unconstrained, but gpu limit=1 must serialize them
    results = dag.execute(max_workers=5, resource_limits={"gpu": 1})

    assert len(results) == 5
    assert max_active_gpu_seen == 1
    assert results["task_3"] == 6


def test_dag_resource_limit_exceeded_validation():
    """Verify validation fails if a node requires more than total available resource."""
    dag = JobDAG()
    dag.add_node("heavy", lambda: 42, resources={"gpu": 2})

    with pytest.raises(ValueError, match="exceeding limit of 1"):
        dag.execute(resource_limits={"gpu": 1})


def _process_task_add(a: int, b: int) -> int:
    return a + b


def _process_task_mul(a: int, b: int) -> int:
    return a * b


def test_dag_event_driven_dispatch_speed():
    """Event-driven dispatch wakes immediately on task completion without sleep latency."""
    dag = JobDAG()
    prev = None
    for i in range(12):
        nid = f"step_{i}"
        deps = [prev] if prev else []
        dag.add_node(nid, lambda: 1, dependencies=deps)
        prev = nid

    t0 = time.perf_counter()
    results = dag.execute(max_workers=4)
    elapsed = time.perf_counter() - t0

    assert len(results) == 12
    assert results["step_11"] == 1
    # 12 sequential tasks with 5ms sleep wait would take at least 60ms; event-driven should be much faster
    assert elapsed < 0.05


def test_dag_deadlock_detection_on_unallocatable_resources():
    """If ready_queue contains tasks that cannot be allocated and no futures are running, deadlock is raised."""
    dag = JobDAG()

    def step1():
        # Dynamically mutate downstream task resource demand to exceed total capacity
        dag.nodes["step2"].resources["custom_res"] = 10
        return 1

    def step2():
        return 2

    dag.add_node("step1", step1, resources={"custom_res": 1})
    dag.add_node("step2", step2, dependencies=["step1"], resources={"custom_res": 1})

    with pytest.raises(RuntimeError, match="Deadlock: ready_queue contains tasks that cannot be allocated with available resources"):
        dag.execute(resource_limits={"custom_res": 2})


def test_dag_process_pool_backend():
    """DAG execution using backend='process' (ProcessPoolExecutor)."""
    dag = JobDAG()
    dag.add_node("n1", _process_task_add, (), {}, 10, 20)
    dag.add_node("n2", _process_task_mul, (), {}, 6, 7)

    results = dag.execute(max_workers=2, backend="process")
    assert results["n1"] == 30
    assert results["n2"] == 42


def test_dag_ready_queue_delayed_dispatch():
    """Verify ready_queue tasks waiting for resources are dispatched as running tasks free them."""
    dag = JobDAG()
    exec_order = []
    lock = __import__("threading").Lock()

    def make_task(name: str):
        def _task():
            with lock:
                exec_order.append(name)
            time.sleep(0.01)
            return name
        return _task

    # 4 independent ready tasks, but capacity allows only 2 concurrently
    for i in range(4):
        dag.add_node(f"task_{i}", make_task(f"task_{i}"), resources={"slot": 1})

    results = dag.execute(max_workers=4, resource_limits={"slot": 2})
    assert len(results) == 4
    for i in range(4):
        assert results[f"task_{i}"] == f"task_{i}"
    assert len(exec_order) == 4


def test_dag_result_eviction():
    """Intermediate node results are evicted once all downstream dependents finish."""
    dag = JobDAG()
    dag.add_node("upstream", lambda: [1, 2, 3, 4] * 100)
    dag.add_node("downstream1", lambda: len(dag.nodes["upstream"].result), dependencies=["upstream"])
    dag.add_node("downstream2", lambda: sum(dag.nodes["upstream"].result), dependencies=["upstream"])

    results = dag.execute(max_workers=2, evict_results=True)
    # Intermediate node upstream has had its result evicted to free memory
    assert dag.nodes["upstream"].result is None
    # Leaf nodes retain their results
    assert results["downstream1"] == 400
    assert results["downstream2"] == 1000


