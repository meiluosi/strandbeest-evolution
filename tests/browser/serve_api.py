"""Disposable real API for browser regressions; never touches the user's assets."""

import os
import tempfile

import uvicorn

from strandbeest_api.app import create_app


if __name__ == "__main__":
    os.environ["STRANDBEEST_CORS"] = "http://127.0.0.1:4173,http://127.0.0.1:4174"
    with tempfile.TemporaryDirectory(prefix="beest-browser-") as root:
        app = create_app(root, workers=2)
        try:
            uvicorn.run(app, host="0.0.0.0", port=8787, log_level="warning")
        finally:
            app.state.workers.stop()
