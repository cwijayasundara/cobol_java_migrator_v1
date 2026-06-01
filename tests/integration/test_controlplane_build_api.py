"""Build endpoint: inject a stub codegen so the wiring, BRD-prerequisite, scaffold,
file-writing, stage-marking, and response shaping run without a live LLM."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject
from cobol_modernizer.persistence.tables import Base, Workspace, JourneyStage
from cobol_modernizer.controlplane import build as bd
from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_session, get_neo4j


class _FakeNeo4j:
    def __init__(self, has_brd=True):
        self.has_brd = has_brd

    def run(self, query, **params):
        if "RETURN b ORDER BY b.version DESC" in query:
            return [{"b": {"version": 1, "rating": "high"}}] if self.has_brd else []
        return []


def _stub_codegen(slug, *, neo4j, repo_path, brd_json):
    return GeneratedProject(slice_id="posting", files=[
        GeneratedFile(path="src/test/java/com/cobolmodernizer/x/PostingServiceTest.java",
                      kind="test", content="class PostingServiceTest {}",
                      evidence=["CBPOST1M.WRITE-ACCT"]),
        GeneratedFile(path="src/main/java/com/cobolmodernizer/x/PostingService.java",
                      kind="main", content="class PostingService {}",
                      evidence=["CBPOST1M.UPDATE-ACCT"]),
    ])


def _setup(monkeypatch, tmp_path, has_brd=True):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    (tmp_path / "carddemo-mini").mkdir()
    monkeypatch.setenv("COBOL_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("CODEGEN_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(bd, "_generate_slice_graph", _stub_codegen)

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="x"))
        s.add(JourneyStage(id="stg-build", workspace_id="ws-1", stage_key="build",
                           ordinal=9, status="pending"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss; ss.commit()
        finally:
            ss.close()

    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: _FakeNeo4j(has_brd=has_brd)
    return TestClient(app), eng, tmp_path


def test_build_generates_scaffolds_and_writes_files(monkeypatch, tmp_path):
    c, eng, tp = _setup(monkeypatch, tmp_path)
    try:
        r = c.post("/api/workspaces/ws-1/build").json()
        assert r["slice_id"] == "posting" and r["file_count"] == 2
        assert r["tests"] == 1 and r["mains"] == 1
        assert r["base_package"] == "com.cobolmodernizer.carddemomini"
        assert r["module"] == "carddemo-mini-posting"
        # scaffold + generated files actually on disk
        root = tp / "out" / "carddemo-mini-posting"
        assert (root / "pom.xml").exists()
        assert (root / "src/test/java/com/cobolmodernizer/x/PostingServiceTest.java").read_text() \
            == "class PostingServiceTest {}"
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() == "passed"
    finally:
        app.dependency_overrides.clear()


def test_build_409_without_brd(monkeypatch, tmp_path):
    c, eng, tp = _setup(monkeypatch, tmp_path, has_brd=False)
    try:
        assert c.post("/api/workspaces/ws-1/build").status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_build_503_without_api_key(monkeypatch, tmp_path):
    c, eng, tp = _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    try:
        assert c.post("/api/workspaces/ws-1/build").status_code == 503
    finally:
        app.dependency_overrides.clear()
