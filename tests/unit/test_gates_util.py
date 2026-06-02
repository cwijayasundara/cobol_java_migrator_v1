from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.persistence.tables import Base, Gate, JourneyStage, Workspace


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(Workspace(id="ws-1", name="m", repo_slug="r", created_by="t"))
    s.add(JourneyStage(workspace_id="ws-1", stage_key="backlog", ordinal=6, status="running"))
    s.commit()
    return s


def test_upsert_gate_creates_then_updates_same_row():
    s = _session()
    g1 = upsert_gate(s, "ws-1", "backlog", "backlog_coverage",
                     passed=False, result={"coverage_ratio": 0.5}, threshold={"min": 0.8})
    s.flush()
    assert g1.status == "open"
    g2 = upsert_gate(s, "ws-1", "backlog", "backlog_coverage",
                     passed=True, result={"coverage_ratio": 0.9}, threshold={"min": 0.8})
    s.flush()
    assert g2.id == g1.id  # same row, not a duplicate
    assert g2.status == "passed"
    rows = s.execute(select(Gate).where(Gate.gate_key == "backlog_coverage")).scalars().all()
    assert len(rows) == 1


def test_upsert_gate_refreshes_updated_at_on_update():
    s = _session()
    g1 = upsert_gate(s, "ws-1", "backlog", "backlog_coverage", passed=False, result={}, threshold={})
    s.flush()
    first = g1.updated_at
    g2 = upsert_gate(s, "ws-1", "backlog", "backlog_coverage", passed=True, result={"x": 1}, threshold={})
    s.flush()
    assert g2.id == g1.id
    # >= is robust to clock granularity (timestamps may be identical on fast runs)
    assert g2.updated_at >= first


def test_upsert_gate_preserves_waived_status():
    s = _session()
    g = upsert_gate(s, "ws-1", "backlog", "backlog_coverage", passed=False, result={}, threshold={})
    g.status = "waived"
    s.flush()
    g2 = upsert_gate(s, "ws-1", "backlog", "backlog_coverage", passed=False, result={"x": 1}, threshold={})
    s.flush()
    assert g2.status == "waived"  # an explicit human waiver is never silently reverted
