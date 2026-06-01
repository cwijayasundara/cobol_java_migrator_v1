"""Parse endpoint: run_parse logic + POST /parse, with a fake extractor (no Java)
and a fake Neo4j client (no DB). Proves it ingests, marks stages passed, counts."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.models import CodeEntity, CodeRelationship, EntityKind, ParseResult, RelKind
from cobol_modernizer.persistence.tables import Base, Workspace, JourneyStage
from cobol_modernizer.controlplane import parse as parse_mod
from cobol_modernizer.controlplane.parse import run_parse


def _entity(qn, kind, fp="CBACT01M.cbl"):
    return CodeEntity(kind=kind, qualified_name=qn, simple_name=qn, file_path=fp,
                      start_line=1, end_line=2)


def _results():
    return [ParseResult(
        file_path="CBACT01M.cbl",
        entities=[_entity("CBACT01M", EntityKind.PROGRAM),
                  _entity("ACCOUNT-RECORD", EntityKind.COPYBOOK)],
        relationships=[CodeRelationship(source_qname="CBACT01M", target_qname="ACCTFILE",
                                        kind=RelKind.READS, metadata={"resource": "ACCTFILE"})],
    )]


class _FakeParser:
    def __init__(self, repo_dir, **kw):
        self.repo_dir = repo_dir

    def parse_repo(self):
        return _results()


class _FakeNeo4j:
    def __init__(self):
        self.entities = 0
        self.relationships = 0
        self.schema_applied = False

    def apply_schema(self):
        self.schema_applied = True

    def merge_entity(self, **kw):
        self.entities += 1

    def merge_relationship(self, **kw):
        self.relationships += 1


def _seeded(tmp_path):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = Session(eng)
    ws = Workspace(id="ws-1", name="carddemo-mini", repo_slug="carddemo-mini",
                   created_by="x")
    s.add(ws)
    for i, k in enumerate(["parse", "graph"]):
        s.add(JourneyStage(id=f"stg-{k}", workspace_id="ws-1", stage_key=k,
                           ordinal=i, status="pending"))
    s.commit()
    (tmp_path / "carddemo-mini" / "cbl").mkdir(parents=True)
    (tmp_path / "carddemo-mini" / "cbl" / "CBACT01M.cbl").write_text("x")
    return s, eng, ws


def test_run_parse_ingests_and_marks_stages_passed(tmp_path):
    s, eng, ws = _seeded(tmp_path)
    neo = _FakeNeo4j()
    out = run_parse(session=s, neo4j=neo, workspace=ws, source_root=tmp_path,
                    parser_factory=_FakeParser)
    s.commit()
    assert out["programs"] == 1 and out["copybooks"] == 1
    assert out["entities"] == 2 and out["relationships"] == 1
    assert neo.schema_applied and neo.entities == 2 and neo.relationships == 1
    statuses = {st.stage_key: st.status for st in
                s.execute(select(JourneyStage).where(JourneyStage.workspace_id == "ws-1")).scalars()}
    assert statuses == {"parse": "passed", "graph": "passed"}


def test_run_parse_404_when_repo_dir_missing(tmp_path):
    import pytest
    from fastapi import HTTPException
    s, eng, ws = _seeded(tmp_path)
    ws.repo_slug = "does-not-exist"
    with pytest.raises(HTTPException) as ei:
        run_parse(session=s, neo4j=_FakeNeo4j(), workspace=ws, source_root=tmp_path,
                  parser_factory=_FakeParser)
    assert ei.value.status_code == 404


def test_parse_endpoint_200(tmp_path, monkeypatch):
    s, eng, ws = _seeded(tmp_path)
    monkeypatch.setenv("COBOL_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setattr(parse_mod, "CobolParser", _FakeParser)
    from cobol_modernizer.api import app
    from cobol_modernizer.controlplane.deps import get_session, get_neo4j

    def _session_override():
        yield s

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_neo4j] = lambda: _FakeNeo4j()
    try:
        r = TestClient(app).post("/api/workspaces/ws-1/parse")
        assert r.status_code == 200, r.text
        assert r.json()["entities"] == 2
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_neo4j, None)
