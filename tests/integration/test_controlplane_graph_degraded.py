"""Graph endpoints degrade gracefully (clean 503, no 500 traceback) when the
Neo4j backing store is unreachable/misconfigured. No live Neo4j needed — the
get_neo4j dependency is overridden with a client whose .run raises."""
from fastapi.testclient import TestClient
from neo4j.exceptions import AuthError, ServiceUnavailable

from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_neo4j


class _RaisingClient:
    def __init__(self, exc):
        self._exc = exc

    def run(self, *args, **kwargs):
        raise self._exc


def _override(exc):
    app.dependency_overrides[get_neo4j] = lambda: _RaisingClient(exc)
    return TestClient(app)


def test_graph_returns_503_on_auth_failure():
    client = _override(AuthError("The client is unauthorized due to authentication failure."))
    try:
        r = client.get("/api/graph?repo=x&limit=10")
        assert r.status_code == 503
        assert "unavailable" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_neo4j, None)


def test_entity_returns_503_on_service_unavailable():
    client = _override(ServiceUnavailable("cannot connect"))
    try:
        r = client.get("/api/entity/CBACT01C")
        assert r.status_code == 503
    finally:
        app.dependency_overrides.pop(get_neo4j, None)
