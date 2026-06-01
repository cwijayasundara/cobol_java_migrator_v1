"""Seams + Plan endpoints: monkeypatch rank_candidates (no live Neo4j) so the
endpoint wiring, stage-marking, and the REAL deterministic plan DAG logic
(stories_from_seam_set + derive_dependencies + topo_order) are exercised."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.seam.schema import (
    SeamCandidate, SeamSignals, SeamScore, SeamType, TransitionPattern,
)
from cobol_modernizer.persistence.tables import Base, Workspace, JourneyStage
from cobol_modernizer.controlplane import analysis as analysis_mod
from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_session, get_neo4j


def _cand(program, seam_type, weighted, writer=False):
    return SeamCandidate(
        program=program, seam_type=seam_type,
        signals=SeamSignals(business=0.5, isolation=0.5, testability=0.5,
                            data_ownership=0.5, risk=0.2),
        score=SeamScore(weighted=weighted, normalized={}),
        transition=TransitionPattern(name="extract_product_lines", summary="…"),
        evidence_map={"E1": [program]}, identity_drift_writer=writer,
    ).model_dump(mode="json")


_CANDS = [
    _cand("CBACT01M", SeamType.db_reader, 0.82),
    _cand("CBPOST1M", SeamType.db_writer, 0.41, writer=True),
]


def _client(monkeypatch, cands=_CANDS):
    monkeypatch.setattr(analysis_mod, "rank_candidates", lambda client, *, repo, limit=25: list(cands))
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="x"))
        for i, k in enumerate(["seams", "plan"]):
            s.add(JourneyStage(id=f"stg-{k}", workspace_id="ws-1", stage_key=k,
                               ordinal=i, status="pending"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss
            ss.commit()
        finally:
            ss.close()

    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: object()
    return TestClient(app), eng


def _stage_status(eng, key):
    with Session(eng) as s:
        return s.execute(select(JourneyStage.status).where(
            JourneyStage.workspace_id == "ws-1", JourneyStage.stage_key == key)).scalar_one()


def test_seams_ranks_and_marks_stage(monkeypatch):
    c, eng = _client(monkeypatch)
    try:
        r = c.post("/api/workspaces/ws-1/seams").json()
        assert r["count"] == 2
        assert r["candidates"][0]["program"] == "CBACT01M"
        assert r["candidates"][0]["seam_type"] == "db_reader"
        assert _stage_status(eng, "seams") == "passed"
    finally:
        app.dependency_overrides.clear()


def test_plan_builds_story_dag_and_marks_stage(monkeypatch):
    c, eng = _client(monkeypatch)
    try:
        r = c.post("/api/workspaces/ws-1/plan").json()
        assert r["acyclic"] is True
        seams = {s["seam"] for s in r["stories"]}
        assert seams == {"CBACT01M", "CBPOST1M"}
        assert len(r["topo_order"]) == len(r["stories"])
        assert _stage_status(eng, "plan") == "passed"
    finally:
        app.dependency_overrides.clear()


def test_seams_409_when_graph_empty(monkeypatch):
    c, eng = _client(monkeypatch, cands=[])
    try:
        assert c.post("/api/workspaces/ws-1/seams").status_code == 409
    finally:
        app.dependency_overrides.clear()


class _DesignNeo4j:
    def run(self, query, **params):
        if "WRITES" in query and "p.kind = 'Program'" in query:
            return [{"program": "CBPOST1M", "writes": ["ACCTFILE", "TRANFILE"]},
                    {"program": "CBACT01M", "writes": []},
                    {"program": "CBVALDTM", "writes": []}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": p} for p in ("CBPOST1M", "CBACT01M", "CBVALDTM")]
        return []


def test_design_builds_writer_slice_with_adrs_and_ownership_gate():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="x"))
        s.add(JourneyStage(id="stg-design", workspace_id="ws-1", stage_key="design",
                           ordinal=8, status="pending"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss; ss.commit()
        finally:
            ss.close()

    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: _DesignNeo4j()
    try:
        r = TestClient(app).post("/api/workspaces/ws-1/design").json()
        assert r["count"] == 1                       # only CBPOST1M writes
        d = r["designs"][0]
        assert d["design"]["owned_resources"] == ["ACCTFILE", "TRANFILE"]
        assert d["data_ownership_ok"] is True and d["rating"] == "high"
        assert len(d["adrs"]) == 3
        assert any("mimic" in a["title"].lower() for a in d["adrs"])
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "design")).scalar_one() == "passed"
    finally:
        app.dependency_overrides.clear()
