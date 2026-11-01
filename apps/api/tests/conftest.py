import pytest
from fastapi.testclient import TestClient
from strandbeest_api.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    yield TestClient(app)
    if hasattr(app.state, "workers"):
        app.state.workers.stop()
