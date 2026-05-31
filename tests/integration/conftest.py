import pytest
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.persistence.tables import (
    Base, Workspace, JourneyStage, Gate, Budget, AgentRun, Artifact,
)
from cobol_modernizer.controlplane.deps import get_session

TS = datetime(2026, 5, 30, tzinfo=timezone.utc)


@pytest.fixture
def cp_client():
    """A TestClient with get_session overridden by a seeded in-memory sqlite DB.
    Seeds the canonical workspace mirroring web/src/test/fixtures/controlplane.ts."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as seed:
        seed.add(Workspace(id="ws-1", name="CardDemo", repo_slug="aws-mf-carddemo",
                           graph_snapshot="snap-001", created_by="cwijay@biz2bricks.ai",
                           created_at=TS, status="active"))
        keys = ["outcome", "intake", "parse", "graph", "explore", "blueprint",
                "seams", "plan", "design", "build", "verify"]
        for i, k in enumerate(keys):
            seed.add(JourneyStage(id=f"stg-{k}", workspace_id="ws-1", stage_key=k,
                                  ordinal=i,
                                  status="passed" if i < 5 else "running" if i == 5 else "pending",
                                  updated_at=TS))
        seed.add(Gate(id="gate-brd", workspace_id="ws-1", stage_id="stg-blueprint",
                      gate_key="brd_groundedness", status="open",
                      threshold={"min_weighted": 4.2}, result={"weighted": 4.35},
                      updated_at=TS))
        seed.add(Budget(id="bud-1", workspace_id="ws-1", scope="workspace",
                        agent_run_id=None, cap_usd=Decimal("50"),
                        spent_usd=Decimal("18.42"), killed=False, updated_at=TS))
        seed.add(AgentRun(id="run-1", workspace_id="ws-1", stage_id="stg-blueprint",
                          role="brd", model="claude-sonnet-4-6", status="running",
                          started_by="cwijay@biz2bricks.ai", started_at=TS,
                          input_tokens=12000, output_tokens=3400,
                          cache_read_tokens=8000, cache_creation_tokens=2000,
                          total_cost_usd=Decimal("0.42")))
        seed.add(Artifact(id="art-brd-1", workspace_id="ws-1", stage_id="stg-blueprint",
                          agent_run_id="run-1", kind="brd", version=1,
                          object_uri="minio://artifacts/ws-1/brd/v1.html",
                          content_hash="sha256:abc",
                          evidence_map={"REQ-001": ["CBACT01C", "CBACT01C.1000-MAIN"]},
                          created_at=TS))
        seed.commit()

    from cobol_modernizer.api import app

    def _override():
        s = Session(engine)
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_session, None)
