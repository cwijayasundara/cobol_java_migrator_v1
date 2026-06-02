from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Workspace


class FakeNeo4j:
    def run(self, query, **params):
        if "HAS_BRD" in query:
            return [{"b": {"version": 1, "sections": "[]", "evidence_map": "{}"}}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "CBPOST1M"}]
        return []


def test_backlog_status_idle_before_generation():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="mini", repo_slug="carddemo-mini", created_by="tester"))
        s.commit()

    def session_override():
        ss = Session(eng)
        try:
            yield ss
        finally:
            ss.close()

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: FakeNeo4j()
    try:
        client = TestClient(app)
        response = client.get("/api/workspaces/ws-1/backlog")
        assert response.status_code == 200
        assert response.json()["status"] == "idle"
    finally:
        app.dependency_overrides.clear()
