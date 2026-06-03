"""Build endpoint: inject a stub codegen so the wiring, prerequisite prechecks,
scaffold, file-writing, stage-marking, and response shaping run without a live LLM.

`POST /build` dispatches on CODEGEN_MODE (default `story` -> the story engine;
`legacy_slice` -> the original one-shot slice path). The legacy-slice tests pin
CODEGEN_MODE=legacy_slice explicitly and inject `_generate_slice_graph`; the story
tests run the default and inject the heavy story-run step so the response-shape
mapping + stage-marking + generated_test_refs run without a live LLM/Maven."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject
from cobol_modernizer.codegen.story_plan import StoryCodegenStatus
from cobol_modernizer.persistence.tables import Base, Workspace, JourneyStage
from cobol_modernizer.controlplane import build as bd
from cobol_modernizer.controlplane import build_stories as bs
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_session, get_neo4j


# A minimal technical design (one service, one resource) the story scaffold + specs
# loader can reconstruct; backlog/domain are the smallest valid shapes.
_BACKLOG = {"version": 1, "epics_json": "[]", "stories_json": "[]"}
_DOMAIN = {"version": 1, "rating": "medium", "contexts_json": "[]",
           "designs_json": "[]"}
_TECHNICAL = {"version": 1, "services_json":
              '[{"name": "Posting", "bounded_context": "posting", '
              '"deployment": "module", "story_ids": [], '
              '"api_contracts": [], "persistence": []}]'}


class _FakeNeo4j:
    """Answers the Cypher the build prechecks/briefs run. `has_brd` toggles the BRD;
    `has_specs` toggles the backlog/domain/technical specs (story-mode prereqs).
    The typed-spec storages call `get_latest` on this same object, so it doubles as a
    storage backend by intercepting their queries."""

    def __init__(self, has_brd=True, has_specs=True):
        self.has_brd = has_brd
        self.has_specs = has_specs

    def run(self, query, **params):
        if "HAS_BACKLOG" in query or "RETURN b ORDER BY b.version DESC" in query:
            return [{"b": _BACKLOG}] if self.has_specs else []
        if "HAS_TECHNICAL_DESIGN" in query:
            return [{"t": _TECHNICAL}] if self.has_specs else []
        return []


def _patch_storages(monkeypatch, fake):
    """The typed-spec loaders go through BRDStorage/BacklogStorage/DomainDesignStorage/
    TechnicalDesignStorage `get_latest`, not raw Cypher, so stub them to honor the
    fake's `has_brd`/`has_specs` flags."""
    from cobol_modernizer.brd import storage as brd_storage
    from cobol_modernizer.backlog import storage as backlog_storage
    from cobol_modernizer.controlplane import domain as domain_mod
    from cobol_modernizer.technical_design import storage as td_storage

    monkeypatch.setattr(brd_storage.BRDStorage, "get_latest",
                        lambda self, slug: ({"version": 1, "rating": "high"}
                                            if fake.has_brd else None))
    monkeypatch.setattr(backlog_storage.BacklogStorage, "get_latest",
                        lambda self, slug: (_BACKLOG if fake.has_specs else None))
    monkeypatch.setattr(domain_mod.DomainDesignStorage, "get_latest",
                        lambda self, slug: (_DOMAIN if fake.has_specs else None))
    monkeypatch.setattr(td_storage.TechnicalDesignStorage, "get_latest",
                        lambda self, slug: (_TECHNICAL if fake.has_specs else None))


def _stub_codegen(slug, *, neo4j, repo_path, brd_json):
    return GeneratedProject(slice_id="posting", files=[
        GeneratedFile(path="src/test/java/com/cobolmodernizer/x/PostingServiceTest.java",
                      kind="test", content="class PostingServiceTest {}",
                      evidence=["CBPOST1M.WRITE-ACCT"]),
        GeneratedFile(path="src/main/java/com/cobolmodernizer/x/PostingService.java",
                      kind="main", content="class PostingService {}",
                      evidence=["CBPOST1M.UPDATE-ACCT"]),
    ])


class _StoryResult:
    def __init__(self, story_id, status):
        self.story_id = story_id
        self.status = status
        self.attempts = 1


def _stub_story_step(out_root):
    """A stub for the injectable heavy story-run step. Scaffolds nothing heavy: it just
    writes a couple of Java files into a module dir so the summary scan finds them, and
    returns acceptable per-story results so `_gate_stage` passes."""
    def _step(*, session, neo4j, workspace, source_root, output_root, plan, story_id):
        from cobol_modernizer.codegen.scaffold_from_design import module_name_for
        root = output_root / module_name_for(workspace.repo_slug)
        (root / "src/main/java/x").mkdir(parents=True, exist_ok=True)
        (root / "src/test/java/x").mkdir(parents=True, exist_ok=True)
        (root / "src/main/java/x/PostingService.java").write_text(
            "class PostingService {}", encoding="utf-8")
        (root / "src/test/java/x/PostingServiceTest.java").write_text(
            "class PostingServiceTest {}", encoding="utf-8")
        return {
            "repo_slug": workspace.repo_slug, "module_dir": str(root),
            "story_id": story_id, "story_count": 1,
            "results": [{"story_id": "US-1",
                         "status": StoryCodegenStatus.passed.value, "attempts": 1}],
        }
    return _step


def _setup(monkeypatch, tmp_path, *, mode, has_brd=True, has_specs=True):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CODEGEN_MODE", mode)
    (tmp_path / "carddemo-mini").mkdir()
    monkeypatch.setenv("COBOL_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("CODEGEN_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(bd, "_generate_slice_graph", _stub_codegen)

    fake = _FakeNeo4j(has_brd=has_brd, has_specs=has_specs)
    _patch_storages(monkeypatch, fake)
    if mode == "story":
        monkeypatch.setattr(bs, "_run_story_build_step",
                            _stub_story_step(tmp_path / "out"))

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

    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_session", lambda: Session(eng))
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    return TestClient(app), eng, tmp_path


# --------------------------------------------------------------------------- #
# Mode switch (`_codegen_mode`) — the default-routing contract is `story`       #
# --------------------------------------------------------------------------- #
def test_codegen_mode_defaults_to_story_when_env_absent(monkeypatch):
    # The spec's headline guarantee: POST /build routes through the story engine
    # by default. With no CODEGEN_MODE set, the switch resolves to `story`.
    monkeypatch.delenv("CODEGEN_MODE", raising=False)
    assert bd._codegen_mode() == "story"


def test_codegen_mode_unrecognized_value_falls_back_to_story(monkeypatch):
    # An unrecognized value is not an error — it degrades to the story default so a
    # typo can never silently route to the legacy escape hatch.
    monkeypatch.setenv("CODEGEN_MODE", "garbage")
    assert bd._codegen_mode() == "story"


def test_codegen_mode_legacy_slice_is_honored(monkeypatch):
    monkeypatch.setenv("CODEGEN_MODE", "legacy_slice")
    assert bd._codegen_mode() == "legacy_slice"


# --------------------------------------------------------------------------- #
# Legacy-slice mode (the escape hatch) — original behavior, pinned explicitly  #
# --------------------------------------------------------------------------- #
def test_legacy_slice_generates_scaffolds_and_writes_files(monkeypatch, tmp_path):
    c, eng, tp = _setup(monkeypatch, tmp_path, mode="legacy_slice")
    try:
        resp = c.post("/api/workspaces/ws-1/build")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "done"
        r = body["result"]
        assert r["slice_id"] == "posting" and r["file_count"] == 2
        assert r["tests"] == 1 and r["mains"] == 1
        assert r["base_package"] == "com.cobolmodernizer.carddemomini"
        assert r["module"] == "carddemo-mini-posting"
        # scaffold + generated files actually on disk
        root = tp / "out" / "carddemo-mini-posting"
        assert (root / "pom.xml").exists()
        assert (root / "src/test/java/com/cobolmodernizer/x/PostingServiceTest.java").read_text() \
            == "class PostingServiceTest {}"
        # GET status reflects the finished job
        st = c.get("/api/workspaces/ws-1/build").json()
        assert st["status"] == "done" and st["result"]["module"] == "carddemo-mini-posting"
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() == "passed"
    finally:
        app.dependency_overrides.clear()


def test_legacy_slice_409_without_brd(monkeypatch, tmp_path):
    c, eng, tp = _setup(monkeypatch, tmp_path, mode="legacy_slice", has_brd=False)
    try:
        assert c.post("/api/workspaces/ws-1/build").status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_legacy_slice_does_not_require_story_specs(monkeypatch, tmp_path):
    # legacy mode only needs a BRD — a repo with no backlog/domain/technical still builds
    c, eng, tp = _setup(monkeypatch, tmp_path, mode="legacy_slice", has_specs=False)
    try:
        assert c.post("/api/workspaces/ws-1/build").status_code == 202
    finally:
        app.dependency_overrides.clear()


def test_build_503_without_api_key(monkeypatch, tmp_path):
    c, eng, tp = _setup(monkeypatch, tmp_path, mode="legacy_slice")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    try:
        assert c.post("/api/workspaces/ws-1/build").status_code == 503
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Story mode (the DEFAULT) — routes /build through the story engine            #
# --------------------------------------------------------------------------- #
def test_story_mode_is_default_and_returns_compatible_summary(monkeypatch, tmp_path):
    # No CODEGEN_MODE override beyond setting "story" — proves the default path shape.
    c, eng, tp = _setup(monkeypatch, tmp_path, mode="story")
    try:
        resp = c.post("/api/workspaces/ws-1/build")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "done", body
        r = body["result"]
        # legacy BuildResult keys are all present + sensibly defaulted
        assert r["repo_slug"] == "carddemo-mini"
        assert r["slice_id"] == "stories"
        assert r["module"] == "carddemo-mini"
        assert r["base_package"] == "com.cobolmodernizer.carddemomini"
        assert r["file_count"] == 2 and r["tests"] == 1 and r["mains"] == 1
        assert r["evidence_map"] == {}
        assert {f["kind"] for f in r["files"]} == {"test", "main"}
        # the per-story summary the story engine produced is surfaced too
        assert r["stories"] == [{"story_id": "US-1", "status": "passed", "attempts": 1}]
        # stage marked passed by run_story_build's gate
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() == "passed"
    finally:
        app.dependency_overrides.clear()


def test_story_mode_409_without_backlog(monkeypatch, tmp_path):
    # story mode needs backlog/domain/technical — missing specs gives a clear 409.
    c, eng, tp = _setup(monkeypatch, tmp_path, mode="story", has_specs=False)
    try:
        resp = c.post("/api/workspaces/ws-1/build")
        assert resp.status_code == 409
        assert "backlog" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_story_mode_409_without_brd(monkeypatch, tmp_path):
    c, eng, tp = _setup(monkeypatch, tmp_path, mode="story", has_brd=False)
    try:
        assert c.post("/api/workspaces/ws-1/build").status_code == 409
    finally:
        app.dependency_overrides.clear()
