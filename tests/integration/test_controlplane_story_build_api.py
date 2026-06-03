"""Story-build endpoints: prove the deterministic plan path (no LLM), the
prechecks, the one-job-per-workspace guard, the injected story-run orchestration,
and the persisted per-story status surface — all without a live LLM/Maven/Neo4j.

A FakeNeo4j answers the backlog/domain/technical/BRD loader queries; the heavy
story-run step is injected (exactly like the build test injects
`_generate_slice_graph`), so the endpoints/prechecks/job-guard/response-shaping
run in-process."""
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.codegen import story_storage
from cobol_modernizer.controlplane import build_stories as bs
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, JourneyStage, Workspace


# --------------------------------------------------------------------------- #
# Spec fixtures: a backlog (2 stories, one depending on the other), a domain   #
# design (one context + aggregate), a technical design (one service mapping     #
# both stories). Serialized the way the storages persist (model_dump json).     #
# --------------------------------------------------------------------------- #
_STORIES = [
    {"id": "US-2", "epic_id": "E1", "title": "Post", "actor": "system",
     "narrative": "post a txn", "acceptance_criteria": [{"id": "AC-2", "statement": "x"}],
     "depends_on": ["US-1"], "evidence_refs": ["CBPOST1M.UPDATE-ACCT"], "context": "Posting"},
    {"id": "US-1", "epic_id": "E1", "title": "Validate", "actor": "system",
     "narrative": "validate a txn", "acceptance_criteria": [{"id": "AC-1", "statement": "y"}],
     "depends_on": [], "evidence_refs": ["CBPOST1M.VALIDATE"], "context": "Posting"},
]
_EPICS = [{"id": "E1", "title": "Posting", "outcome": "o", "story_ids": ["US-1", "US-2"]}]
_CONTEXTS = [{"name": "Posting", "business_capability": "post txns",
              "member_programs": ["CBPOST1M"]}]
_DESIGNS = [{"context": "Posting",
             "aggregates": [{"name": "Posting", "root_entity": "Account",
                             "invariants": ["balance >= 0"], "methods": ["post"]}],
             "cobol_mapping": [{"cobol_ref": "CBPOST1M.WRITE", "maps_to": "Account.post"}]}]
_SERVICES = [{"name": "PostingService", "bounded_context": "Posting",
              "deployment": "module", "story_ids": ["US-1", "US-2"],
              "api_contracts": [{"name": "PostTxn", "method": "POST", "path": "/post"}],
              "persistence": [{"resource": "Account", "access_pattern": "repository"}],
              "evidence_refs": ["CBPOST1M"]}]


class _FakeNeo4j:
    """Answers the four loader queries (backlog/domain/technical/BRD) the planner
    and prechecks make. Each toggle drops the corresponding spec to exercise a
    precheck failure."""

    def __init__(self, *, has_brd=True, has_backlog=True, has_domain=True,
                 has_technical=True):
        self.has_brd = has_brd
        self.has_backlog = has_backlog
        self.has_domain = has_domain
        self.has_technical = has_technical

    def run(self, query, **params):
        if "HAS_BACKLOG" in query:
            if not self.has_backlog:
                return []
            return [{"b": {"version": 1, "epics_json": json.dumps(_EPICS),
                           "stories_json": json.dumps(_STORIES)}}]
        if "HAS_DOMAIN_DESIGN" in query:
            if not self.has_domain:
                return []
            return [{"d": {"version": 1, "rating": "high",
                           "contexts_json": json.dumps(_CONTEXTS),
                           "designs_json": json.dumps(_DESIGNS)}}]
        if "HAS_TECHNICAL_DESIGN" in query:
            if not self.has_technical:
                return []
            return [{"t": {"version": 1, "services_json": json.dumps(_SERVICES)}}]
        if "HAS_BRD" in query:
            return [{"b": {"version": 1, "rating": "high"}}] if self.has_brd else []
        return []


class _StubRun:
    """Injectable stand-in for the real scaffold+pack+run_story_plan step. Records
    its calls and returns a `results` list (the shape `run_story_build` gates the
    stage on). `status_for` maps a story id -> its returned status; unmapped stories
    default to `passed`, so by default the gate passes and the stage is marked."""

    def __init__(self, status_for: dict[str, str] | None = None):
        self.calls = []
        self.status_for = status_for or {}

    def __call__(self, *, session, neo4j, workspace, source_root, output_root,
                 plan, story_id):
        self.calls.append({"story_id": story_id,
                           "story_ids": [i.story_id for i in plan.items]})
        items = ([i for i in plan.items if i.story_id == story_id]
                 if story_id is not None else list(plan.items))
        return {"results": [{"story_id": i.story_id,
                             "status": self.status_for.get(i.story_id, "passed"),
                             "attempts": 1} for i in items]}


def _setup(monkeypatch, tmp_path, *, has_brd=True, has_backlog=True,
           has_domain=True, has_technical=True, make_repo_dir=True,
           status_for=None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    if make_repo_dir:
        (tmp_path / "carddemo-mini").mkdir()
    monkeypatch.setenv("COBOL_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("CODEGEN_OUTPUT_DIR", str(tmp_path / "out"))

    stub = _StubRun(status_for=status_for)
    monkeypatch.setattr(bs, "_run_story_build_step", stub)

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
            yield ss
            ss.commit()
        finally:
            ss.close()

    fake = _FakeNeo4j(has_brd=has_brd, has_backlog=has_backlog,
                      has_domain=has_domain, has_technical=has_technical)
    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_session", lambda: Session(eng))
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    return TestClient(app), eng, tmp_path, stub


# --------------------------------------------------------------------------- #
# GET story-plan — deterministic, no LLM, no key required                     #
# --------------------------------------------------------------------------- #
def test_story_plan_returns_ordered_items_no_llm(monkeypatch, tmp_path):
    c, eng, tp, stub = _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # plan is LLM-free
    try:
        resp = c.get("/api/workspaces/ws-1/build/story-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["repo_slug"] == "carddemo-mini"
        ids = [i["story_id"] for i in body["items"]]
        # dependency order: US-1 before US-2 (US-2 depends_on US-1)
        assert ids == ["US-1", "US-2"]
        us2 = next(i for i in body["items"] if i["story_id"] == "US-2")
        assert us2["service_name"] == "PostingService"
        assert us2["bounded_context"] == "Posting"
        assert "AC-2" in us2["acceptance_criteria_ids"]
        assert stub.calls == []  # no codegen ran
    finally:
        app.dependency_overrides.clear()


def test_story_plan_409_without_backlog(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path, has_backlog=False)
    try:
        r = c.get("/api/workspaces/ws-1/build/story-plan")
        assert r.status_code == 409
        assert "backlog" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_story_plan_409_without_domain(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path, has_domain=False)
    try:
        r = c.get("/api/workspaces/ws-1/build/story-plan")
        assert r.status_code == 409
        assert "domain" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_story_plan_409_without_technical(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path, has_technical=False)
    try:
        r = c.get("/api/workspaces/ws-1/build/story-plan")
        assert r.status_code == 409
        assert "technical" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Prechecks on the run endpoints                                              #
# --------------------------------------------------------------------------- #
def test_run_404_without_repo_dir(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path, make_repo_dir=False)
    try:
        assert c.post("/api/workspaces/ws-1/build/stories").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_run_409_without_brd(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path, has_brd=False)
    try:
        r = c.post("/api/workspaces/ws-1/build/stories")
        assert r.status_code == 409
        assert "brd" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_run_409_without_backlog(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path, has_backlog=False)
    try:
        assert c.post("/api/workspaces/ws-1/build/stories").status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_run_409_without_domain(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path, has_domain=False)
    try:
        assert c.post("/api/workspaces/ws-1/build/stories").status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_run_409_without_technical(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path, has_technical=False)
    try:
        assert c.post("/api/workspaces/ws-1/build/stories").status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_run_503_without_api_key(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    try:
        assert c.post("/api/workspaces/ws-1/build/stories").status_code == 503
        assert c.post("/api/workspaces/ws-1/build/stories/US-1").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_run_404_unknown_workspace(monkeypatch, tmp_path):
    c, *_ = _setup(monkeypatch, tmp_path)
    try:
        assert c.post("/api/workspaces/nope/build/stories").status_code == 404
        assert c.get("/api/workspaces/nope/build/story-plan").status_code == 404
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# POST run endpoints — 202 + injected stub orchestration ran + stage marked    #
# --------------------------------------------------------------------------- #
def test_post_all_stories_runs_injected_orchestration(monkeypatch, tmp_path):
    c, eng, tp, stub = _setup(monkeypatch, tmp_path)
    try:
        resp = c.post("/api/workspaces/ws-1/build/stories")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "done"
        assert len(stub.calls) == 1
        assert stub.calls[0]["story_id"] is None  # all-stories run
        assert stub.calls[0]["story_ids"] == ["US-1", "US-2"]  # ordered plan
        with Session(eng) as s:
            from sqlalchemy import select
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() == "passed"
    finally:
        app.dependency_overrides.clear()


def test_post_single_story_runs_injected_orchestration(monkeypatch, tmp_path):
    c, eng, tp, stub = _setup(monkeypatch, tmp_path)
    try:
        resp = c.post("/api/workspaces/ws-1/build/stories/US-1")
        assert resp.status_code == 202
        assert resp.json()["status"] == "done"
        assert len(stub.calls) == 1
        assert stub.calls[0]["story_id"] == "US-1"
    finally:
        app.dependency_overrides.clear()


def test_post_single_story_404_unknown_story(monkeypatch, tmp_path):
    c, eng, tp, stub = _setup(monkeypatch, tmp_path)
    try:
        r = c.post("/api/workspaces/ws-1/build/stories/NOPE")
        assert r.status_code == 404
        assert stub.calls == []
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Stage gating — the stage passes ONLY when every story is acceptable          #
# --------------------------------------------------------------------------- #
def test_failed_story_fails_job_and_does_not_mark_stage(monkeypatch, tmp_path):
    # US-2 fails; run_story_plan never raises, so without gating the job would end
    # `done` and the stage `passed` — a silently broken build. Gating must fail it.
    c, eng, tp, stub = _setup(monkeypatch, tmp_path, status_for={"US-2": "failed"})
    from sqlalchemy import select
    try:
        resp = c.post("/api/workspaces/ws-1/build/stories")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "failed"
        assert "failed" in (body["error"] or "")
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() != "passed"
        # The per-story status map is still surfaced via the job error path / GET.
        st = c.get("/api/workspaces/ws-1/build/stories").json()
        assert st["job"]["status"] == "failed"
    finally:
        app.dependency_overrides.clear()


def test_all_generated_unverified_still_passes_stage(monkeypatch, tmp_path):
    # Toolchain-absent (mvn missing) yields generated_unverified — the degrade
    # contract: that MUST NOT fail the build. Stage passes; job ends done.
    c, eng, tp, stub = _setup(
        monkeypatch, tmp_path,
        status_for={"US-1": "generated-unverified", "US-2": "generated-unverified"})
    from sqlalchemy import select
    try:
        resp = c.post("/api/workspaces/ws-1/build/stories")
        assert resp.status_code == 202
        assert resp.json()["status"] == "done"
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() == "passed"
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Pass-with-deferred — a `deferred` story does NOT wedge the build             #
# --------------------------------------------------------------------------- #
def test_deferred_story_passes_stage_with_counts_surfaced(monkeypatch, tmp_path):
    # US-2 exhausted its retry/budget allotment in the repeat-until-done loop and is
    # terminal `deferred` (NOT a hard error). The gate must PASS (never wedge on one
    # bad story) AND surface progress counts so the operator sees what happened.
    c, eng, tp, stub = _setup(monkeypatch, tmp_path,
                              status_for={"US-2": "deferred"})
    from sqlalchemy import select
    try:
        resp = c.post("/api/workspaces/ws-1/build/stories")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "done", body
        # Counts surfaced so the operator sees real progress.
        result = body["result"]["result"]
        assert result["pass_count"] == 1
        assert result["deferred_count"] == 1
        # `pending` = outstanding work (deferred + skipped); the one deferred story.
        assert result["pending"] == 1
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() == "passed"
    finally:
        app.dependency_overrides.clear()


def test_error_story_still_fails_gate(monkeypatch, tmp_path):
    # A genuine `error`/`failed` story (distinct from `deferred`) STILL fails the gate —
    # deferred is tolerated, error is not.
    c, eng, tp, stub = _setup(monkeypatch, tmp_path,
                              status_for={"US-2": "error"})
    from sqlalchemy import select
    try:
        resp = c.post("/api/workspaces/ws-1/build/stories")
        assert resp.status_code == 202
        assert resp.json()["status"] == "failed"
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() != "passed"
    finally:
        app.dependency_overrides.clear()


def test_all_deferred_fails_gate_nothing_genuinely_built(monkeypatch, tmp_path):
    # The gate requires at least one GENUINELY built story (passed/generated-unverified).
    # If EVERY story is deferred, nothing was built — the build must NOT pass.
    c, eng, tp, stub = _setup(
        monkeypatch, tmp_path,
        status_for={"US-1": "deferred", "US-2": "deferred"})
    from sqlalchemy import select
    try:
        resp = c.post("/api/workspaces/ws-1/build/stories")
        assert resp.status_code == 202
        assert resp.json()["status"] == "failed"
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "build")).scalar_one() != "passed"
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Restart-fresh — a second POST regenerates ALL stories (no cross-run resume)  #
# --------------------------------------------------------------------------- #
class _ResumeAwareStub:
    """A stub that mimics the real loop's cross-run RESUME behaviour: any story with an
    accepted persisted `story_codegen_status` record is returned `skipped`; everything
    else is freshly `passed` (and persisted). This lets the test observe whether the
    restart-fresh re-trigger truly regenerates (a fresh run must clear prior accepted
    records, so NO story comes back `skipped` on the second POST)."""

    def __init__(self):
        self.calls = []

    def __call__(self, *, session, neo4j, workspace, source_root, output_root,
                 plan, story_id):
        items = ([i for i in plan.items if i.story_id == story_id]
                 if story_id is not None else list(plan.items))
        results = []
        statuses = []
        for i in items:
            prior = story_storage.get_story_record(session, workspace.id, i.story_id)
            if prior and prior.get("status") in {"passed", "generated-unverified",
                                                 "skipped"}:
                status = "skipped"
            else:
                status = "passed"
                story_storage.record_story_status(
                    session, workspace_id=workspace.id, story_id=i.story_id,
                    payload={"status": status, "attempts": 1})
            statuses.append(status)
            results.append({"story_id": i.story_id, "status": status, "attempts": 1})
        self.calls.append({"story_id": story_id, "statuses": statuses})
        return {"results": results}


def test_second_post_regenerates_all_stories_restart_fresh(monkeypatch, tmp_path):
    # Default BUILD_RESUME=0: a second trigger starts a NEW run that regenerates EVERY
    # story — it must NOT skip them all as already-done from the prior run's persisted
    # accepted records. A resume-aware stub returns `skipped` for any story whose prior
    # record is accepted; restart-fresh must clear those so the second run rebuilds all.
    c, eng, tp, _ = _setup(monkeypatch, tmp_path)
    resume_stub = _ResumeAwareStub()
    monkeypatch.setattr(bs, "_run_story_build_step", resume_stub)
    try:
        r1 = c.post("/api/workspaces/ws-1/build/stories")
        assert r1.status_code == 202 and r1.json()["status"] == "done"
        r2 = c.post("/api/workspaces/ws-1/build/stories")
        assert r2.status_code == 202 and r2.json()["status"] == "done"
        assert len(resume_stub.calls) == 2
        # First run: all freshly built. Second run (restart-fresh): NOT all skipped —
        # the prior accepted records were cleared, so every story is rebuilt.
        assert resume_stub.calls[0]["statuses"] == ["passed", "passed"]
        assert resume_stub.calls[1]["statuses"] == ["passed", "passed"]
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# One-job-per-workspace guard                                                 #
# --------------------------------------------------------------------------- #
def test_one_job_guard(monkeypatch, tmp_path):
    c, eng, tp, stub = _setup(monkeypatch, tmp_path)
    # Make the job "stick" as running so the second POST sees it in-flight.
    monkeypatch.setattr(jobs.runner, "inline", False)

    def _never(*a, **k):
        import time
        time.sleep(5)
        return {}
    monkeypatch.setattr(bs, "_run_story_build_step", _never)
    try:
        r1 = c.post("/api/workspaces/ws-1/build/stories")
        r2 = c.post("/api/workspaces/ws-1/build/stories")
        assert r1.status_code == 202 and r2.status_code == 202
        # Both observe the SAME single running job (no second job spawned).
        assert r1.json()["status"] == "running"
        assert r2.json()["status"] == "running"
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# GET stories — persisted per-story status map + job view                     #
# --------------------------------------------------------------------------- #
def test_get_stories_returns_status_map_and_job(monkeypatch, tmp_path):
    c, eng, tp, stub = _setup(monkeypatch, tmp_path)
    try:
        # Seed a persisted per-story status artifact.
        with Session(eng) as s:
            story_storage.record_story_status(
                s, workspace_id="ws-1", story_id="US-1",
                payload={"status": "passed", "attempts": 1})
            s.commit()
        resp = c.get("/api/workspaces/ws-1/build/stories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["stories"]["US-1"]["status"] == "passed"
        assert body["job"]["status"] == "idle"
    finally:
        app.dependency_overrides.clear()


def test_get_stories_empty_when_nothing_recorded(monkeypatch, tmp_path):
    c, eng, tp, stub = _setup(monkeypatch, tmp_path)
    try:
        body = c.get("/api/workspaces/ws-1/build/stories").json()
        assert body["stories"] == {}
        assert body["job"]["status"] == "idle"
    finally:
        app.dependency_overrides.clear()
