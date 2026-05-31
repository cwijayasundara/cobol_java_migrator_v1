from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.persistence.tables import (
    Base, Workspace, JourneyStage, Gate, Budget, AgentRun, Artifact, AgentRunEvent,
)
from cobol_modernizer.controlplane.seed import seed_demo, DEMO_REPO_SLUG


def _session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return Session(eng)


def test_seed_creates_full_demo_journey():
    s = _session()
    ws = seed_demo(s); s.commit()
    assert ws.repo_slug == DEMO_REPO_SLUG
    stages = s.execute(select(JourneyStage).where(JourneyStage.workspace_id == ws.id)).scalars().all()
    assert len(stages) == 11
    assert s.execute(select(Gate).where(Gate.workspace_id == ws.id)).scalars().first().gate_key == "brd_groundedness"
    assert s.execute(select(Budget).where(Budget.workspace_id == ws.id)).scalars().first().cap_usd == 50
    run = s.execute(select(AgentRun).where(AgentRun.workspace_id == ws.id)).scalars().first()
    assert run.status == "running"
    events = s.execute(select(AgentRunEvent).where(AgentRunEvent.run_id == run.id)).scalars().all()
    assert [e.seq for e in events] == [0, 1]
    assert s.execute(select(Artifact).where(Artifact.workspace_id == ws.id)).scalars().first().kind == "brd"


def test_seed_is_idempotent():
    s = _session()
    a = seed_demo(s); s.commit()
    b = seed_demo(s); s.commit()
    assert a.id == b.id
    assert len(s.execute(select(Workspace)).scalars().all()) == 1
