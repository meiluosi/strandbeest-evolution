"""Exercise an installed API over HTTP without pytest or an existing data directory.

Used in a fresh virtual environment and in the API container. Network traffic stays
on loopback; designs, jobs and telemetry are discarded with the temporary directory.
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import urllib.request

import pyarrow as pa
import uvicorn

from strandbeest_api import create_app
from strandbeest_common.schemas import schema_dir, validate


def main() -> None:
    design = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())
    with tempfile.TemporaryDirectory(prefix="beest-install-smoke-") as data_dir:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        app = create_app(data_dir, workers=1)
        base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()

        def request(path: str, body: dict | None = None, *, binary: bool = False):
            payload = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(base + path, data=payload, headers={"Content-Type": "application/json"})
            # The smoke test must not use a machine's HTTP proxy for localhost.
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as response:
                data = response.read()
                return data if binary else json.loads(data)

        def run_job(path: str, body: dict) -> dict:
            job_id = request(path, body)["job_id"]
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                job = request(f"/jobs/{job_id}")
                if job["status"] == "done":
                    return job["result"]
                if job["status"] in {"failed", "cancelled"}:
                    raise RuntimeError(f"{path}: {job}")
                time.sleep(0.05)
            raise TimeoutError(f"{path}: job {job_id} did not complete")

        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("installed API did not start")
                time.sleep(0.02)
            request("/health")
            atlas = run_job("/evolve/qd", {"design": design, "evals": 50, "bins": [4, 4], "seed": 42})
            validate("atlas", atlas)
            assert atlas["cells_filled"] > 0 and atlas["evals"] == 50, atlas
            result = run_job("/runs", {
                "design": design, "ensemble": False,
                "overrides": {"run": {"revolutions": 0.1, "settle": 0.05}},
            })
            validate("run", result)
            stream = request(f"/runs/{result['id']}/telemetry.arrow", binary=True)
            table = pa.ipc.open_stream(stream).read_all()
            assert table.num_rows > 0 and {"t", "pos", "quat", "psi", "torque"}.issubset(table.column_names)
            assert table.schema.metadata and b"meta" in table.schema.metadata
            print(json.dumps({"installed_api": "passed", "qd_evals": atlas["evals"],
                              "atlas_cells": atlas["cells_filled"], "telemetry_rows": table.num_rows}))
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            app.state.workers.stop()
            sock.close()
            if thread.is_alive():
                raise RuntimeError("installed API did not shut down")


if __name__ == "__main__":
    main()
