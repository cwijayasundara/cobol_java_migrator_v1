"""graph-summary endpoint: counts per repo via a fake Neo4j; 404 for unknown ws."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.persistence.tables import Base, Workspace
from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_session, get_neo4j


class _FakeNeo4j:
    def run(self, query, **params):
        if "RETURN n.kind AS kind" in query:
            return [{"kind": "Program", "c": 3}, {"kind": "DataItem", "c": 20}]
        if "count(x) AS c" in query:
            return [{"c": 29}]
        return []


def _client():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="x"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss
        finally:
            ss.close()

    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: _FakeNeo4j()
    return TestClient(app)


def test_graph_summary_counts():
    c = _client()
    try:
        body = c.get("/api/workspaces/ws-1/graph-summary").json()
        assert body["entities"] == 23 and body["relationships"] == 29
        assert body["by_kind"]["Program"] == 3
        assert c.get("/api/workspaces/nope/graph-summary").status_code == 404
    finally:
        app.dependency_overrides.clear()
