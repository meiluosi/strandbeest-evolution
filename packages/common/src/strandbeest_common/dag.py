"""DAG job scheduling and asynchronous ask/tell optimization engine (ADR-0004, E5-04).

Decouples optimization algorithms, parameter sweeps, and multi-stage evaluation pipelines
from underlying compute backends via standard DAG dependencies and resource tags.
"""

from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence


def _execute_job_node(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Top-level helper for executing job node functions in thread or process pool."""
    return fn(*args, **kwargs)


class OptimizerProtocol(Protocol):
    best: Any
    best_f: float

    def ask(self) -> list[Any]: ...
    def tell(self, xs: Sequence[Any], fs: Sequence[float]) -> None: ...
    def stop(self) -> bool: ...


@dataclass
class JobNode:
    """A single computation node in a DAG."""

    id: str
    fn: Callable[..., Any]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    dependencies: set[str] = field(default_factory=set)
    resources: dict[str, int] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed, cancelled
    result: Any = None
    error: Exception | None = None


class JobDAG:
    """A directed acyclic graph of jobs executed with dependency resolution and concurrency limits."""

    def __init__(self) -> None:
        self.nodes: dict[str, JobNode] = {}

    def add_node(
        self,
        id: str,
        fn: Callable[..., Any],
        dependencies: Sequence[str] = (),
        resources: Mapping[str, int] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> JobNode:
        if id in self.nodes:
            raise ValueError(f"duplicate node id '{id}'")
        node = JobNode(
            id=id,
            fn=fn,
            args=args,
            kwargs=kwargs,
            dependencies=set(dependencies),
            resources=dict(resources or {"cpu": 1}),
        )
        self.nodes[id] = node
        return node

    def validate(self) -> list[str]:
        """Validate DAG acyclicity and return a topological ordering of node ids."""
        in_degree: dict[str, int] = {k: 0 for k in self.nodes}
        adj: dict[str, list[str]] = defaultdict(list)

        for nid, node in self.nodes.items():
            for dep in node.dependencies:
                if dep not in self.nodes:
                    raise ValueError(f"node '{nid}' depends on non-existent node '{dep}'")
                adj[dep].append(nid)
                in_degree[nid] += 1

        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        order = []
        while queue:
            curr = queue.popleft()
            order.append(curr)
            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self.nodes):
            cycle_nodes = [nid for nid, deg in in_degree.items() if deg > 0]
            raise ValueError(f"cycle detected in DAG involving nodes: {cycle_nodes}")
        return order

    def execute(
        self,
        max_workers: int = 4,
        resource_limits: Mapping[str, int] | None = None,
        progress_cb: Callable[[int, int, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        backend: str = "thread",
        evict_results: bool = False,
    ) -> dict[str, Any]:
        """Execute the DAG concurrently according to dependencies and resource limits."""
        self.validate()  # Ensure acyclic before execution

        if resource_limits is not None:
            for nid, node in self.nodes.items():
                for res_name, qty in node.resources.items():
                    limit = resource_limits.get(res_name)
                    if limit is not None and qty > limit:
                        raise ValueError(
                            f"node '{nid}' requests {qty} of resource '{res_name}', exceeding limit of {limit}"
                        )

        if backend == "thread":
            executor_cls = ThreadPoolExecutor
        elif backend == "process":
            executor_cls = ProcessPoolExecutor
        else:
            raise ValueError(f"unsupported backend '{backend}', expected 'thread' or 'process'")

        lock = threading.Lock()
        completed_count = 0
        total_nodes = len(self.nodes)

        # Build reverse dependency graph
        dependents: dict[str, list[str]] = defaultdict(list)
        unmet_dependencies: dict[str, int] = {}
        for nid, node in self.nodes.items():
            unmet_dependencies[nid] = len(node.dependencies)
            for dep in node.dependencies:
                dependents[dep].append(nid)

        remaining_dependents: dict[str, int] = {nid: len(dependents[nid]) for nid in self.nodes}

        def _on_node_finished(done_nid: str) -> None:
            if not evict_results:
                return
            for parent_id in self.nodes[done_nid].dependencies:
                remaining_dependents[parent_id] -= 1
                if remaining_dependents[parent_id] == 0 and len(dependents[parent_id]) > 0:
                    self.nodes[parent_id].result = None

        futures: dict[Future, str] = {}
        ready_queue: deque[str] = deque()
        avail_resources: dict[str, int] = dict(resource_limits) if resource_limits is not None else {}

        def can_allocate(node: JobNode) -> bool:
            if resource_limits is None:
                return True
            for r_name, r_qty in node.resources.items():
                if r_name in avail_resources and avail_resources[r_name] < r_qty:
                    return False
            return True

        def allocate_resources(node: JobNode) -> None:
            if resource_limits is not None:
                for r_name, r_qty in node.resources.items():
                    if r_name in avail_resources:
                        avail_resources[r_name] -= r_qty

        def release_resources(node: JobNode) -> None:
            if resource_limits is not None:
                for r_name, r_qty in node.resources.items():
                    if r_name in avail_resources:
                        avail_resources[r_name] += r_qty

        with executor_cls(max_workers=max_workers) as executor:

            def submit_node(nid: str) -> None:
                node = self.nodes[nid]
                node.status = "running"
                fut = executor.submit(_execute_job_node, node.fn, node.args, node.kwargs)
                futures[fut] = nid

            def dispatch_ready() -> None:
                if is_cancelled and is_cancelled():
                    while ready_queue:
                        cand_id = ready_queue.popleft()
                        cand_node = self.nodes[cand_id]
                        cand_node.status = "cancelled"
                    return

                deferred = []
                while ready_queue:
                    cand_id = ready_queue.popleft()
                    cand_node = self.nodes[cand_id]
                    if can_allocate(cand_node):
                        allocate_resources(cand_node)
                        submit_node(cand_id)
                    else:
                        deferred.append(cand_id)
                ready_queue.extend(deferred)

            # Enqueue initial ready nodes
            for nid, unmet in unmet_dependencies.items():
                if unmet == 0:
                    ready_queue.append(nid)

            dispatch_ready()

            while futures or ready_queue:
                # If no futures are running, but ready_queue still has tasks, check if any can be allocated
                if not futures:
                    dispatch_ready()
                    if not futures and ready_queue:
                        raise RuntimeError(
                            "Deadlock: ready_queue contains tasks that cannot be allocated with available resources"
                        )
                    if not futures:
                        break

                # Wait for any future to finish without busy-wait sleeping
                done_futs, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)

                for fut in done_futs:
                    nid = futures.pop(fut)
                    node = self.nodes[nid]
                    release_resources(node)

                    if is_cancelled and is_cancelled():
                        node.status = "cancelled"
                    else:
                        try:
                            node.result = fut.result()
                            node.status = "completed"
                        except Exception as exc:
                            node.error = exc
                            node.status = "failed"

                    with lock:
                        completed_count += 1
                        if progress_cb:
                            progress_cb(completed_count, total_nodes, f"{completed_count}/{total_nodes} nodes done")

                    _on_node_finished(nid)

                    # If node succeeded, unblock dependents
                    if node.status == "completed":
                        for dep_id in dependents[nid]:
                            unmet_dependencies[dep_id] -= 1
                            if unmet_dependencies[dep_id] == 0:
                                ready_queue.append(dep_id)
                    else:
                        # Cancel all downstream dependents if a node fails/cancels
                        queue = deque(dependents[nid])
                        while queue:
                            curr_dep = queue.popleft()
                            dep_node = self.nodes[curr_dep]
                            if dep_node.status == "pending":
                                dep_node.status = "cancelled"
                                dep_node.error = RuntimeError(f"dependency '{nid}' failed or was cancelled")
                                completed_count += 1
                                _on_node_finished(curr_dep)
                                queue.extend(dependents[curr_dep])

                dispatch_ready()

        return {nid: node.result for nid, node in self.nodes.items()}


class AskTellScheduler:
    """Asynchronous optimizer evaluation harness running on a worker pool."""

    def __init__(
        self,
        optimizer: OptimizerProtocol,
        eval_fn: Callable[[Any], float],
        max_workers: int = 4,
        max_evals: int = 100,
    ) -> None:
        self.optimizer = optimizer
        self.eval_fn = eval_fn
        self.max_workers = max_workers
        self.max_evals = max_evals
        self.total_evals = 0

    def step(self) -> list[tuple[Any, float]]:
        """Ask for a candidate batch, evaluate concurrently, and tell results back."""
        candidates = self.optimizer.ask()
        if not candidates:
            return []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            scores = list(pool.map(self.eval_fn, candidates))

        self.optimizer.tell(candidates, scores)
        self.total_evals += len(candidates)
        return list(zip(candidates, scores))

    def run_until_stop(
        self,
        progress_cb: Callable[[int, float], None] | None = None,
    ) -> tuple[Any, float]:
        """Run iterations until optimizer.stop() or max_evals reached."""
        while not self.optimizer.stop() and self.total_evals < self.max_evals:
            self.step()
            if progress_cb:
                progress_cb(self.total_evals, self.optimizer.best_f)
        return self.optimizer.best, self.optimizer.best_f
