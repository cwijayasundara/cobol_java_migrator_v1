"""Unit tests for the story runner (Task 6). No live LLM / Maven / Neo4j — every
heavy dependency is injected: a fake AgentRunner, canned gen_tests/gen_impl
returning StoryPatch, a scripted run_tests returning StoryTestResult sequences, an
in-memory SQLite session, and a patched (incrementing) clock."""
from __future__ import annotations

import asyncio
import itertools

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cobol_modernizer.codegen.schema import GeneratedFile
from cobol_modernizer.codegen.story_context import build_story_context
from cobol_modernizer.codegen.patch_agent import StoryPatch
from cobol_modernizer.codegen.story_plan import StoryCodegenItem, StoryCodegenStatus
from cobol_modernizer.codegen.budget import BuildBudget, StoryBudget
from cobol_modernizer.codegen.story_runner import (
    build_max_concurrency, run_story, run_story_plan, run_story_plan_until_done,
)
from cobol_modernizer.codegen.story_storage import (
    STORY_CODEGEN_STATUS_KIND, get_status_map, get_story_record,
)
from cobol_modernizer.codegen.test_runner import StoryTestResult, StoryTestStatus
from cobol_modernizer.backlog.schema import AcceptanceCriterion, UserStory
from cobol_modernizer.persistence.tables import Artifact, Base, Workspace


# --------------------------------------------------------------------------- #
# Fixtures / stubs                                                            #
# --------------------------------------------------------------------------- #
class FakeRunner:
    """Stand-in AgentRunner exposing the telemetry surface the runner snapshots."""

    def __init__(self):
        self.token_usage = {"input": 0, "output": 0, "cache_read": 0,
                            "cache_creation": 0}
        self.cost_usd = 0.0
        self.calls = []

    async def run_structured(self, **kwargs):  # pragma: no cover - not used directly
        return {}


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    s.add(Workspace(id="ws1", name="w", repo_slug="carddemo-mini",
                    created_by="tester"))
    s.flush()
    yield s
    s.close()


def _clock():
    """A deterministic monotonic clock: each call advances by 1.0s."""
    return itertools.count(start=0.0, step=1.0).__next__


def _item(story_id="US-1", ac_ids=("AC-1",), cobol_refs=("CBPOST1M",)):
    return StoryCodegenItem(
        story_id=story_id, bounded_context="Posting", service_name="posting-service",
        acceptance_criteria_ids=list(ac_ids), cobol_refs=list(cobol_refs))


def _pack(item):
    story = UserStory(
        id=item.story_id, epic_id="E-1", actor="user",
        title="Post a transaction", narrative="As a user...", context="Posting",
        acceptance_criteria=[AcceptanceCriterion(id=a, statement=f"crit {a}")
                             for a in item.acceptance_criteria_ids])
    return build_story_context(
        item, story=story, service=None, aggregate=None, brd_requirements=[],
        completed_summaries=[], source_pack="COBOL HERE")


def _test_patch(story_id="US-1", ac_ids=("AC-1",)):
    """A canned tests StoryPatch whose content cites the story + AC ids so the AC
    scan finds them. Paths are story-scoped so plan runs don't clobber each other."""
    body = f"// {story_id} " + " ".join(ac_ids) + f"\nclass Post{story_id}Test {{}}"
    return StoryPatch(
        files=[GeneratedFile(
            path=f"src/test/java/com/example/Post{story_id}Test.java", kind="test",
            content=body, evidence=list(ac_ids))],
        rationale="tests for posting")


def _impl_patch(story_id="US-1", cobol_refs=("CBPOST1M",)):
    """A canned impl StoryPatch whose content cites the story id + a cobol ref so the
    lineage gate passes. Story-scoped path."""
    body = (f"// story {story_id} grounded in {cobol_refs[0]}\n"
            f"class Post{story_id} {{}}")
    return StoryPatch(
        files=[GeneratedFile(
            path=f"src/main/java/com/example/Post{story_id}.java", kind="main",
            content=body, evidence=[story_id, cobol_refs[0]])],
        rationale="impl for posting")


def _result(status, **kw):
    return StoryTestResult(status=status, **kw)


def _scripted(*statuses):
    """A run_tests stub returning the given StoryTestResults (or statuses) in order;
    records the module_dir + target it was called with for ordering assertions."""
    results = [s if isinstance(s, StoryTestResult) else _result(s) for s in statuses]
    calls = []
    it = iter(results)

    def run(module_dir, target, **kw):
        calls.append({"module_dir": module_dir, "target": target})
        return next(it)

    run.calls = calls
    return run


def _make_gen_tests(patch=None, recorder=None):
    async def gen(**kwargs):
        if recorder is not None:
            recorder.append(("tests", kwargs))
        if patch is not None:
            return patch
        item = kwargs["item"]
        return _test_patch(story_id=item.story_id,
                           ac_ids=tuple(item.acceptance_criteria_ids))
    return gen


def _make_gen_impl(patch=None, recorder=None):
    async def gen(**kwargs):
        if recorder is not None:
            recorder.append(("impl", kwargs))
        if patch is not None:
            return patch
        item = kwargs["item"]
        refs = tuple(item.cobol_refs) or ("CBPOST1M",)
        return _impl_patch(story_id=item.story_id, cobol_refs=refs)
    return gen


# --------------------------------------------------------------------------- #
# Lifecycle order                                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_lifecycle_tests_before_impl_then_green(session, tmp_path):
    item = _item()
    order = []
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out = await run_story(
        item, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack=_pack(item), runner=FakeRunner(),
        gen_tests=_make_gen_tests(recorder=order),
        gen_impl=_make_gen_impl(recorder=order),
        run_tests=run, now=_clock())
    assert out.status == StoryCodegenStatus.passed
    # tests generated before impl
    assert [k for k, _ in order] == ["tests", "impl"]
    # red baseline recorded; one impl attempt; tests written before first mvn run
    assert out.red_status == StoryTestStatus.tests_failed
    assert out.attempts == 1
    assert (tmp_path / "src/test/java/com/example/PostUS-1Test.java").exists()
    assert (tmp_path / "src/main/java/com/example/PostUS-1.java").exists()


@pytest.mark.asyncio
async def test_targeted_test_class_derived_from_test_files(session, tmp_path):
    item = _item()
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    await run_story(item, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(item), runner=FakeRunner(),
                    gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
                    run_tests=run, now=_clock())
    assert run.calls[0]["target"] == "PostUS-1Test"


# --------------------------------------------------------------------------- #
# Fix 1: a 'running' status is emitted the instant a story starts              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_running_status_emitted_at_start(session, tmp_path):
    """The cockpit's GET /build/stories must reflect an in-flight story. run_story
    records `status: running` the moment it starts (before any gen call returns), so
    a reader sees it BEFORE the terminal status overwrites it. We observe it from
    INSIDE gen_tests (which runs after the running-status write)."""
    item = _item()
    observed: dict = {}

    async def gen_tests(**kwargs):
        # The running status must already be persisted/visible by now.
        observed["rec"] = get_story_record(session, "ws1", item.story_id)
        return _test_patch(story_id=item.story_id,
                           ac_ids=tuple(item.acceptance_criteria_ids))

    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=FakeRunner(), gen_tests=gen_tests,
                          gen_impl=_make_gen_impl(), run_tests=run, now=_clock())
    assert observed["rec"] is not None
    assert observed["rec"]["status"] == "running"
    # The terminal status overwrites 'running' — no stale record remains.
    assert out.status == StoryCodegenStatus.passed
    assert get_story_record(session, "ws1", item.story_id)["status"] == "passed"


@pytest.mark.asyncio
async def test_running_status_not_written_when_persist_false(session, tmp_path):
    """The running-status write is guarded by `persist` like the terminal write."""
    item = _item()
    observed: dict = {}

    async def gen_tests(**kwargs):
        observed["rec"] = get_story_record(session, "ws1", item.story_id)
        return _test_patch(story_id=item.story_id,
                           ac_ids=tuple(item.acceptance_criteria_ids))

    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    await run_story(item, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(item), runner=FakeRunner(),
                    gen_tests=gen_tests, gen_impl=_make_gen_impl(), run_tests=run,
                    now=_clock(), persist=False)
    assert observed["rec"] is None  # nothing persisted when persist=False
    assert get_story_record(session, "ws1", item.story_id) is None


# --------------------------------------------------------------------------- #
# Fix 4: default build concurrency lowered 4 -> 2                              #
# --------------------------------------------------------------------------- #
def test_build_max_concurrency_default_is_two(monkeypatch):
    monkeypatch.delenv("BUILD_MAX_CONCURRENCY", raising=False)
    assert build_max_concurrency() == 2


def test_build_max_concurrency_env_override(monkeypatch):
    monkeypatch.setenv("BUILD_MAX_CONCURRENCY", "5")
    assert build_max_concurrency() == 5


# --------------------------------------------------------------------------- #
# Status mapping table                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_green_first_pass_passed(session, tmp_path):
    item = _item()
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=FakeRunner(), gen_tests=_make_gen_tests(),
                          gen_impl=_make_gen_impl(), run_tests=run, now=_clock())
    assert out.status == StoryCodegenStatus.passed
    assert out.attempts == 1


@pytest.mark.asyncio
async def test_repair_then_green_passes_after_second_impl(session, tmp_path):
    item = _item()
    order = []
    # red baseline, red after impl#1, green after impl#2
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.tests_failed,
                    StoryTestStatus.ok)
    out = await run_story(
        item, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack=_pack(item), runner=FakeRunner(),
        gen_tests=_make_gen_tests(recorder=order),
        gen_impl=_make_gen_impl(recorder=order),
        run_tests=run, repair_max_attempts=2, now=_clock())
    assert out.status == StoryCodegenStatus.passed
    assert out.attempts == 2
    # impl regenerated on repair; the repair pass got the failing-log feedback
    impl_calls = [kw for k, kw in order if k == "impl"]
    assert len(impl_calls) == 2
    assert "repair_feedback" not in impl_calls[0] or impl_calls[0].get("repair_feedback") is None
    assert impl_calls[1]["repair_feedback"]["failing_gate"] == "tests-failed"


@pytest.mark.asyncio
async def test_still_red_after_budget_failed(session, tmp_path):
    item = _item()
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.tests_failed,
                    StoryTestStatus.tests_failed)
    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=FakeRunner(), gen_tests=_make_gen_tests(),
                          gen_impl=_make_gen_impl(), run_tests=run,
                          repair_max_attempts=1, now=_clock())
    assert out.status == StoryCodegenStatus.failed
    assert out.attempts == 2  # first impl + 1 repair


# --------------------------------------------------------------------------- #
# Cost gate — the repair loop stops early when the token/wall budget is over    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_token_budget_stops_repair_loop_early_and_fails(session, tmp_path):
    item = _item()
    runner = FakeRunner()
    impl_calls = []

    async def gen_impl(**kwargs):
        impl_calls.append(kwargs)
        # Each impl pass burns 1000 tokens — after the first pass cumulative usage
        # (1000) is already over the tiny 500-token budget, so the repair loop must
        # break BEFORE issuing a second gen_impl.
        runner.token_usage["output"] += 1000
        return _impl_patch()

    # Never green — left to itself the loop would run repair_max_attempts(=3) repairs.
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.tests_failed,
                    StoryTestStatus.tests_failed, StoryTestStatus.tests_failed)
    budget = StoryBudget(max_tokens=500, max_wall_s=0.0, max_repair_attempts=3)
    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=runner, gen_tests=_make_gen_tests(),
                          gen_impl=gen_impl, run_tests=run, repair_max_attempts=3,
                          budget=budget, now=_clock())
    # Only the FIRST impl pass ran — the loop broke on budget before any repair.
    assert len(impl_calls) == 1
    assert out.attempts == 1  # fewer than repair_max_attempts + 1 (= 4)
    assert out.status == StoryCodegenStatus.failed
    assert "over budget" in out.rationale
    # The durable record reflects the over-budget stop, not a phantom "tests still red".
    rec = get_story_record(session, "ws1", "US-1")
    assert rec["status"] == "failed"
    assert "over budget" in rec["rationale"]


@pytest.mark.asyncio
async def test_wall_budget_stops_repair_loop_early(session, tmp_path):
    item = _item()
    # The _clock() advances 1.0s per call; wall budget of 2.0s is exceeded after a few
    # telemetry/clock ticks, so the repair loop stops before burning all attempts.
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.tests_failed,
                    StoryTestStatus.tests_failed, StoryTestStatus.tests_failed,
                    StoryTestStatus.tests_failed)
    budget = StoryBudget(max_tokens=0, max_wall_s=2.0, max_repair_attempts=5)
    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=FakeRunner(), gen_tests=_make_gen_tests(),
                          gen_impl=_make_gen_impl(), run_tests=run,
                          repair_max_attempts=5, budget=budget, now=_clock())
    assert out.status == StoryCodegenStatus.failed
    assert out.attempts < 6  # broke before exhausting repair_max_attempts + 1
    assert "over budget" in out.rationale


@pytest.mark.asyncio
async def test_toolchain_unavailable_generated_unverified(session, tmp_path):
    item = _item()
    run = _scripted(StoryTestStatus.toolchain_unavailable,
                    StoryTestStatus.toolchain_unavailable)
    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=FakeRunner(), gen_tests=_make_gen_tests(),
                          gen_impl=_make_gen_impl(), run_tests=run, now=_clock())
    assert out.status == StoryCodegenStatus.generated_unverified
    # toolchain_unavailable is not repaired (re-running mvn won't help)
    assert out.attempts == 1


@pytest.mark.asyncio
async def test_ac_coverage_miss_failed_even_when_green(session, tmp_path):
    item = _item(ac_ids=("AC-1", "AC-2"))
    # tests cite only AC-1, so AC-2 is uncovered -> failed despite GREEN
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out = await run_story(
        item, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack=_pack(item), runner=FakeRunner(),
        gen_tests=_make_gen_tests(patch=_test_patch(ac_ids=("AC-1",))),
        gen_impl=_make_gen_impl(), run_tests=run, now=_clock())
    assert out.status == StoryCodegenStatus.failed
    assert out.ac_missing == ["AC-2"]
    assert out.ac_covered == ["AC-1"]


@pytest.mark.asyncio
async def test_missing_lineage_failed_even_when_green(session, tmp_path):
    item = _item()
    # impl cites neither the story id nor a cobol ref -> lineage gate fails
    bad_impl = StoryPatch(files=[GeneratedFile(
        path="src/main/java/com/example/Post.java", kind="main",
        content="class Post {}", evidence=[])])
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=FakeRunner(), gen_tests=_make_gen_tests(),
                          gen_impl=_make_gen_impl(patch=bad_impl), run_tests=run,
                          now=_clock())
    assert out.status == StoryCodegenStatus.failed


# --------------------------------------------------------------------------- #
# BASIC resume                                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_resume_skips_passed_story_with_same_hash(session, tmp_path):
    item = _item()
    pack = _pack(item)
    run1 = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out1 = await run_story(item, session=session, workspace_id="ws1",
                           module_dir=tmp_path, context_pack=pack,
                           runner=FakeRunner(), gen_tests=_make_gen_tests(),
                           gen_impl=_make_gen_impl(), run_tests=run1, now=_clock())
    assert out1.status == StoryCodegenStatus.passed

    # Re-run with the SAME context_hash -> skipped; gen/test seams must NOT be called.
    def _boom(*a, **k):
        raise AssertionError("seam should not run on resume-skip")

    async def _aboom(**k):
        raise AssertionError("LLM seam should not run on resume-skip")

    out2 = await run_story(item, session=session, workspace_id="ws1",
                           module_dir=tmp_path, context_pack=pack,
                           runner=FakeRunner(), gen_tests=_aboom, gen_impl=_aboom,
                           run_tests=_boom, now=_clock())
    assert out2.status == StoryCodegenStatus.skipped
    assert out2.skipped is True


@pytest.mark.asyncio
async def test_resume_reruns_on_changed_hash(session, tmp_path):
    item = _item()
    run1 = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    await run_story(item, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(item), runner=FakeRunner(),
                    gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
                    run_tests=run1, now=_clock())
    # different source -> different context_hash -> NOT skipped
    item2 = _item()
    story = UserStory(id=item2.story_id, epic_id="E-1", actor="user", title="t",
                      narrative="n", context="Posting",
                      acceptance_criteria=[AcceptanceCriterion(id="AC-1", statement="s")])
    changed = build_story_context(item2, story=story, service=None, aggregate=None,
                                  brd_requirements=[], completed_summaries=[],
                                  source_pack="DIFFERENT COBOL")
    run2 = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out = await run_story(item2, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=changed,
                          runner=FakeRunner(), gen_tests=_make_gen_tests(),
                          gen_impl=_make_gen_impl(), run_tests=run2, now=_clock())
    assert out.status == StoryCodegenStatus.passed


@pytest.mark.asyncio
async def test_resume_reruns_a_previously_failed_story(session, tmp_path):
    item = _item()
    pack = _pack(item)
    run1 = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.tests_failed)
    out1 = await run_story(item, session=session, workspace_id="ws1",
                           module_dir=tmp_path, context_pack=pack,
                           runner=FakeRunner(), gen_tests=_make_gen_tests(),
                           gen_impl=_make_gen_impl(), run_tests=run1,
                           repair_max_attempts=0, now=_clock())
    assert out1.status == StoryCodegenStatus.failed
    # failed stories re-run even with the same hash
    run2 = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out2 = await run_story(item, session=session, workspace_id="ws1",
                           module_dir=tmp_path, context_pack=pack,
                           runner=FakeRunner(), gen_tests=_make_gen_tests(),
                           gen_impl=_make_gen_impl(), run_tests=run2, now=_clock())
    assert out2.status == StoryCodegenStatus.passed


# --------------------------------------------------------------------------- #
# Persistence: artifact payload shape + version increment + generated_test_refs #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_persisted_artifact_payload_and_version(session, tmp_path):
    item = _item()
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    await run_story(item, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(item), runner=FakeRunner(),
                    gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
                    run_tests=run, now=_clock(), model="sonnet")
    rec = get_story_record(session, "ws1", "US-1")
    assert rec is not None
    assert rec["status"] == "passed"
    assert rec["model"] == "sonnet"
    assert rec["attempts"] == 1
    assert rec["context_hash"] == _pack(item).context_hash
    assert set(rec["token_usage"]) == {"input", "output", "cache_read", "cache_creation"}
    assert "wall_time_s" in rec and "cost_usd" in rec
    assert rec["changed_files"] == ["src/main/java/com/example/PostUS-1.java"]
    assert rec["test_result"]["status"] == "ok"
    assert rec["ac_covered"] == ["AC-1"]

    arts = session.execute(
        select(Artifact).where(Artifact.kind == STORY_CODEGEN_STATUS_KIND)
    ).scalars().all()
    # Two versions per story now: the 'running' status at start (Fix 1) + the
    # terminal status at the end. The latest version is the terminal one.
    assert max(a.version for a in arts) == 2
    assert arts[0].object_uri == "inline://story_codegen_status"
    assert arts[0].content_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_second_story_increments_version_and_merges_map(session, tmp_path):
    a = _item("US-1")
    b = _item("US-2")
    run_a = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    run_b = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    await run_story(a, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(a), runner=FakeRunner(),
                    gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
                    run_tests=run_a, now=_clock())
    await run_story(b, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(b), runner=FakeRunner(),
                    gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
                    run_tests=run_b, now=_clock())
    m = get_status_map(session, "ws1")
    assert set(m) == {"US-1", "US-2"}
    arts = session.execute(
        select(Artifact).where(Artifact.kind == STORY_CODEGEN_STATUS_KIND)
    ).scalars().all()
    # Each story writes twice now (running + terminal, Fix 1): 2 stories -> v4.
    assert max(art.version for art in arts) == 4


@pytest.mark.asyncio
async def test_generated_test_refs_still_written(session, tmp_path):
    item = _item()
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    await run_story(item, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(item), runner=FakeRunner(),
                    gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
                    run_tests=run, now=_clock())
    refs = session.execute(
        select(Artifact).where(Artifact.kind == "generated_test_refs")
    ).scalars().all()
    assert refs, "generated_test_refs artifact must be written for the Verify gate"
    assert refs[0].evidence_map["acceptance_criteria"] == ["AC-1"]


@pytest.mark.asyncio
async def test_generated_test_refs_cumulative_across_stories(session, tmp_path):
    """BUG 1 (the Verify contract): every story's `_persist` records a NEW
    `generated_test_refs` version filtered to ITS OWN acceptance_criteria_ids. The
    Verify story-behavior gate reads the SINGLE LATEST version and checks it against
    ALL stories' ACs. So the latest version MUST hold the UNION of every story's ACs,
    not just the last story's — otherwise a perfectly-built multi-story run reports
    "missing generated tests" for every story but the last and the gate fails.

    Drive the REAL run_story_plan (no stub) for a 2-story plan with injected non-LLM
    seams (canned JUnit citing each story's AC + green run_tests), then assert the
    latest version's acceptance_criteria == the UNION {AC-1, AC-2}."""
    items = [_item("US-1", ac_ids=("AC-1",)), _item("US-2", ac_ids=("AC-2",))]
    packs = {it.story_id: _pack(it) for it in items}
    statuses = itertools.cycle([StoryTestStatus.tests_failed, StoryTestStatus.ok])

    def run(module_dir, target, **k):
        return _result(next(statuses))

    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, now=_clock())
    assert all(r.status == StoryCodegenStatus.passed for r in results)

    refs = session.execute(
        select(Artifact).where(Artifact.kind == "generated_test_refs")
    ).scalars().all()
    latest = max(refs, key=lambda a: a.version)
    # The LATEST version (what Verify reads) must hold BOTH stories' ACs.
    assert set(latest.evidence_map["acceptance_criteria"]) == {"AC-1", "AC-2"}


# --------------------------------------------------------------------------- #
# Telemetry                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_telemetry_deltas_captured(session, tmp_path):
    item = _item()
    runner = FakeRunner()

    async def gen_tests(**k):
        runner.token_usage["input"] += 100
        runner.cost_usd += 0.01
        return _test_patch()

    async def gen_impl(**k):
        runner.token_usage["output"] += 50
        runner.cost_usd += 0.02
        return _impl_patch()

    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=runner, gen_tests=gen_tests, gen_impl=gen_impl,
                          run_tests=run, now=_clock())
    assert out.token_usage["input"] == 100
    assert out.token_usage["output"] == 50
    assert out.cost_usd == pytest.approx(0.03)
    # clock advances by 1.0 per call: started -> finished spans >0
    assert out.wall_time_s > 0


# --------------------------------------------------------------------------- #
# Plan-level iteration                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_story_plan_runs_in_order(session, tmp_path):
    items = [_item("US-1"), _item("US-2")]
    seen = []

    def context_pack_for(it):
        seen.append(it.story_id)
        return _pack(it)

    # each story: red then green
    statuses = itertools.cycle([StoryTestStatus.tests_failed, StoryTestStatus.ok])

    def run(module_dir, target, **k):
        return _result(next(statuses))

    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=context_pack_for, runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, now=_clock())
    assert [r.story_id for r in results] == ["US-1", "US-2"]
    assert seen == ["US-1", "US-2"]
    assert all(r.status == StoryCodegenStatus.passed for r in results)


@pytest.mark.asyncio
async def test_run_story_plan_threads_completed_summaries(session, tmp_path):
    """BUG 2: `run_story_plan` accumulates already-built story summaries and threads
    them into LATER WAVES' context (so the "Completed Dependencies" pack section is
    actually populated). A two-arg `context_pack_for(item, completed_summaries)`
    receives the prior-wave summaries: empty for wave 0, the wave-0 stories' summaries
    for wave 1. US-2 depends on US-1, so US-1 is wave 0 and US-2 wave 1 — US-2 sees
    US-1's summary."""
    items = [_item("US-1"),
             StoryCodegenItem(story_id="US-2", bounded_context="Posting",
                              service_name="posting-service",
                              acceptance_criteria_ids=["AC-1"],
                              cobol_refs=["CBPOST1M"], depends_on=["US-1"])]
    seen: list[tuple[str, list[str]]] = []

    def context_pack_for(it, completed_summaries):
        seen.append((it.story_id, list(completed_summaries)))
        return build_story_context(
            it,
            story=UserStory(
                id=it.story_id, epic_id="E-1", actor="user", title="t",
                narrative="n", context="Posting",
                acceptance_criteria=[AcceptanceCriterion(id=a, statement=f"c {a}")
                                     for a in it.acceptance_criteria_ids]),
            service=None, aggregate=None, brd_requirements=[],
            completed_summaries=completed_summaries, source_pack="COBOL HERE")

    statuses = itertools.cycle([StoryTestStatus.tests_failed, StoryTestStatus.ok])

    def run(module_dir, target, **k):
        return _result(next(statuses))

    await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=context_pack_for, runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, now=_clock())
    # First story: no completed deps. Second story: US-1's summary is threaded in.
    assert seen[0] == ("US-1", [])
    assert seen[1][0] == "US-2"
    assert len(seen[1][1]) == 1 and "US-1" in seen[1][1][0]


@pytest.mark.asyncio
async def test_run_story_plan_supports_legacy_single_arg_callback(session, tmp_path):
    """The completed-summaries threading is backward compatible: a legacy single-arg
    `context_pack_for(item)` callback still works (it just doesn't receive summaries)."""
    items = [_item("US-1"), _item("US-2")]
    seen: list[str] = []

    def context_pack_for(it):  # single-arg legacy contract
        seen.append(it.story_id)
        return _pack(it)

    statuses = itertools.cycle([StoryTestStatus.tests_failed, StoryTestStatus.ok])
    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=context_pack_for, runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=lambda md, t, **k: _result(next(statuses)), now=_clock())
    assert seen == ["US-1", "US-2"]
    assert all(r.status == StoryCodegenStatus.passed for r in results)


# --------------------------------------------------------------------------- #
# -Dtest= target derived from the public class NAME, not the file stem        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_target_uses_public_class_name_not_file_stem(session, tmp_path):
    item = _item()
    # File stem (PostTests) differs from the public class (PostTest) — Maven matches
    # the class, so -Dtest= MUST be the class name or it would run zero tests forever.
    tests = StoryPatch(files=[GeneratedFile(
        path="src/test/java/com/example/PostTests.java", kind="test",
        content="// US-1 AC-1\npublic class PostTest {}", evidence=["AC-1"])])
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.ok)
    await run_story(item, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(item), runner=FakeRunner(),
                    gen_tests=_make_gen_tests(patch=tests),
                    gen_impl=_make_gen_impl(), run_tests=run, now=_clock())
    assert run.calls[0]["target"] == "PostTest"


# --------------------------------------------------------------------------- #
# Infra `error` status is non-repairable -> failed, budget not burned         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_error_status_breaks_repair_and_maps_to_failed(session, tmp_path):
    item = _item()
    impl_calls = []
    # red baseline, then error after impl#1; error must STOP repair immediately.
    run = _scripted(StoryTestStatus.tests_failed,
                    _result(StoryTestStatus.error, log_excerpt="mvn timed out"))

    async def gen_impl(**kwargs):
        impl_calls.append(kwargs)
        return _impl_patch()

    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=FakeRunner(), gen_tests=_make_gen_tests(),
                          gen_impl=gen_impl, run_tests=run, repair_max_attempts=3,
                          now=_clock())
    assert out.status == StoryCodegenStatus.failed
    # only ONE impl pass — the full repair budget was NOT burned on an infra error
    assert out.attempts == 1
    assert len(impl_calls) == 1
    assert "infra error" in out.rationale
    rec = get_story_record(session, "ws1", "US-1")
    assert rec["status"] == "failed"


@pytest.mark.asyncio
async def test_no_tests_run_repair_feedback_notes_class_name(session, tmp_path):
    item = _item()
    seen_feedback = []
    run = _scripted(StoryTestStatus.tests_failed, StoryTestStatus.no_tests_run,
                    StoryTestStatus.ok)

    async def gen_impl(**kwargs):
        seen_feedback.append(kwargs.get("repair_feedback"))
        return _impl_patch()

    await run_story(item, session=session, workspace_id="ws1", module_dir=tmp_path,
                    context_pack=_pack(item), runner=FakeRunner(),
                    gen_tests=_make_gen_tests(), gen_impl=gen_impl, run_tests=run,
                    repair_max_attempts=2, now=_clock())
    # first impl pass: no feedback; repair pass after no_tests_run carries the note.
    assert seen_feedback[0] is None
    assert seen_feedback[1]["failing_gate"] == "no-tests-run"
    assert "matched zero tests" in seen_feedback[1]["log_excerpt"]


# --------------------------------------------------------------------------- #
# Mid-lifecycle exception -> durable `failed`, plan continues                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_exception_in_run_story_records_failed_and_returns(session, tmp_path):
    item = _item()

    def boom(module_dir, target, **k):
        raise ValueError("simulated empty LLM payload")

    out = await run_story(item, session=session, workspace_id="ws1",
                          module_dir=tmp_path, context_pack=_pack(item),
                          runner=FakeRunner(), gen_tests=_make_gen_tests(),
                          gen_impl=_make_gen_impl(), run_tests=boom, now=_clock())
    assert out.status == StoryCodegenStatus.failed
    assert "simulated empty LLM payload" in out.rationale
    # the failure is DURABLE
    rec = get_story_record(session, "ws1", "US-1")
    assert rec is not None and rec["status"] == "failed"


@pytest.mark.asyncio
async def test_plan_continues_after_a_raising_story(session, tmp_path):
    items = [_item("US-1"), _item("US-2")]
    ran = []

    def context_pack_for(it):
        return _pack(it)

    # US-1's second run_tests raises; US-2 runs red->green normally.
    seq = iter([
        _result(StoryTestStatus.tests_failed),          # US-1 red
        "BOOM",                                          # US-1 impl run -> raise
        _result(StoryTestStatus.tests_failed),          # US-2 red
        _result(StoryTestStatus.ok),                    # US-2 green
    ])

    def run(module_dir, target, **k):
        nxt = next(seq)
        if nxt == "BOOM":
            raise RuntimeError("mvn exploded")
        return nxt

    async def gen_impl(**kwargs):
        ran.append(kwargs["item"].story_id)
        return _impl_patch(story_id=kwargs["item"].story_id)

    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=context_pack_for, runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=gen_impl, run_tests=run, now=_clock())
    assert [r.story_id for r in results] == ["US-1", "US-2"]
    assert results[0].status == StoryCodegenStatus.failed
    assert results[1].status == StoryCodegenStatus.passed
    # US-2 actually ran after US-1 blew up
    assert "US-2" in ran
    assert get_story_record(session, "ws1", "US-1")["status"] == "failed"
    assert get_story_record(session, "ws1", "US-2")["status"] == "passed"


# --------------------------------------------------------------------------- #
# Dependency-wave parallel fan-out                                            #
# --------------------------------------------------------------------------- #
def _dep_item(story_id, *, depends_on=(), ac_ids=("AC-1",), cobol_refs=("CBPOST1M",)):
    return StoryCodegenItem(
        story_id=story_id, bounded_context="Posting", service_name="posting-service",
        acceptance_criteria_ids=list(ac_ids), cobol_refs=list(cobol_refs),
        depends_on=list(depends_on))


class _ConcurrencyTracker:
    """Records the order stories start/finish and the peak number of concurrently
    in-flight stories, so a test can assert wave ordering + bounded concurrency. A
    story counts as in-flight from its first gen call until its last run_tests."""

    def __init__(self):
        self.in_flight = 0
        self.max_in_flight = 0
        self.started: list[str] = []
        self.finished: list[str] = []
        self._active: set[str] = set()

    async def enter(self, story_id):
        if story_id not in self._active:
            self._active.add(story_id)
            self.started.append(story_id)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        # Yield so co-scheduled stories in the same wave actually overlap.
        await asyncio.sleep(0)

    def leave(self, story_id):
        if story_id in self._active:
            self._active.discard(story_id)
            self.finished.append(story_id)
            self.in_flight -= 1


def _tracked_gen_tests(tracker):
    async def gen(**kwargs):
        item = kwargs["item"]
        await tracker.enter(item.story_id)
        return _test_patch(story_id=item.story_id,
                           ac_ids=tuple(item.acceptance_criteria_ids))
    return gen


def _tracked_gen_impl(tracker):
    async def gen(**kwargs):
        item = kwargs["item"]
        await tracker.enter(item.story_id)
        refs = tuple(item.cobol_refs) or ("CBPOST1M",)
        return _impl_patch(story_id=item.story_id, cobol_refs=refs)
    return gen


def _tracked_run_tests(tracker, statuses_by_story=None):
    # Each story runs red->green by default; leave() marks the story finished.
    counts: dict[str, int] = {}

    def run(module_dir, target, **k):
        # Recover the story id from the targeted test class (PostUS-NTest).
        story_id = target.replace("Post", "").replace("Test", "")
        n = counts.get(story_id, 0)
        counts[story_id] = n + 1
        status = StoryTestStatus.tests_failed if n == 0 else StoryTestStatus.ok
        if status == StoryTestStatus.ok:
            tracker.leave(story_id)
        return _result(status)

    return run


@pytest.mark.asyncio
async def test_waves_run_in_dependency_order(session, tmp_path):
    """A 3-wave plan A; B(dep A); C(dep B) must run wave-by-wave: B starts only after
    A's wave finished, C only after B's. With per-wave gather, the start order is the
    wave order."""
    items = [_dep_item("US-1"), _dep_item("US-2", depends_on=["US-1"]),
             _dep_item("US-3", depends_on=["US-2"])]
    tracker = _ConcurrencyTracker()
    packs = {it.story_id: _pack(it) for it in items}
    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_tracked_gen_tests(tracker), gen_impl=_tracked_gen_impl(tracker),
        run_tests=_tracked_run_tests(tracker), now=_clock())
    assert all(r.status == StoryCodegenStatus.passed for r in results)
    # Deterministic downstream ordering preserved (results in plan order).
    assert [r.story_id for r in results] == ["US-1", "US-2", "US-3"]
    # A story starts only after its dependency finished.
    assert tracker.finished.index("US-1") < tracker.started.index("US-2")
    assert tracker.finished.index("US-2") < tracker.started.index("US-3")


@pytest.mark.asyncio
async def test_independent_wave0_stories_overlap(session, tmp_path):
    """Two independent wave-0 stories must run CONCURRENTLY (peak in-flight >= 2) and
    bounded by BUILD_MAX_CONCURRENCY."""
    items = [_dep_item("US-1"), _dep_item("US-2")]
    tracker = _ConcurrencyTracker()
    packs = {it.story_id: _pack(it) for it in items}
    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_tracked_gen_tests(tracker), gen_impl=_tracked_gen_impl(tracker),
        run_tests=_tracked_run_tests(tracker), now=_clock())
    assert all(r.status == StoryCodegenStatus.passed for r in results)
    assert tracker.max_in_flight >= 2  # the two wave-0 stories overlapped


@pytest.mark.asyncio
async def test_concurrency_bounded_by_semaphore(session, tmp_path, monkeypatch):
    """A wave wider than BUILD_MAX_CONCURRENCY must never exceed it in flight."""
    monkeypatch.setenv("BUILD_MAX_CONCURRENCY", "2")
    items = [_dep_item(f"US-{i}") for i in range(1, 6)]  # 5 independent wave-0 stories
    tracker = _ConcurrencyTracker()
    packs = {it.story_id: _pack(it) for it in items}
    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_tracked_gen_tests(tracker), gen_impl=_tracked_gen_impl(tracker),
        run_tests=_tracked_run_tests(tracker), now=_clock())
    assert all(r.status == StoryCodegenStatus.passed for r in results)
    assert tracker.max_in_flight <= 2
    assert tracker.max_in_flight >= 2  # but it DID parallelize up to the cap


@pytest.mark.asyncio
async def test_completed_summaries_only_from_prior_waves(session, tmp_path):
    """Within a wave, stories do NOT see each other's summaries; a wave-k story sees
    the summaries of ALL stories in waves < k. With A,B in wave0 and C in wave1
    (dep A) and D in wave1 (dep B): C and D each see {A,B} but not each other."""
    items = [
        _dep_item("US-A"), _dep_item("US-B"),
        _dep_item("US-C", depends_on=["US-A"]),
        _dep_item("US-D", depends_on=["US-B"]),
    ]
    seen: dict[str, list[str]] = {}

    def context_pack_for(it, completed_summaries):
        seen[it.story_id] = list(completed_summaries)
        return _pack(it)

    statuses = itertools.cycle([StoryTestStatus.tests_failed, StoryTestStatus.ok])

    def run(module_dir, target, **k):
        return _result(next(statuses))

    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=context_pack_for, runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, now=_clock())
    assert all(r.status == StoryCodegenStatus.passed for r in results)
    # Wave 0 stories see nothing.
    assert seen["US-A"] == []
    assert seen["US-B"] == []
    # Wave 1 stories see BOTH wave-0 summaries, but NOT each other.
    c_ids = " ".join(seen["US-C"])
    d_ids = " ".join(seen["US-D"])
    assert "US-A" in c_ids and "US-B" in c_ids
    assert "US-C" not in c_ids and "US-D" not in c_ids
    assert "US-A" in d_ids and "US-B" in d_ids
    assert "US-C" not in d_ids and "US-D" not in d_ids


@pytest.mark.asyncio
async def test_per_story_runner_instances_under_concurrency(session, tmp_path):
    """Each concurrent story gets its OWN runner instance (so per-story telemetry is
    not crosstalked). A `runner_factory` is consulted once per story; the shared
    `runner` passed in is NOT reused for the per-story work."""
    items = [_dep_item("US-1"), _dep_item("US-2")]
    made: list[FakeRunner] = []

    def factory():
        r = FakeRunner()
        made.append(r)
        return r

    statuses = itertools.cycle([StoryTestStatus.tests_failed, StoryTestStatus.ok])

    def run(module_dir, target, **k):
        return _result(next(statuses))

    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: _pack(it), runner=FakeRunner(),
        runner_factory=factory, gen_tests=_make_gen_tests(),
        gen_impl=_make_gen_impl(), run_tests=run, now=_clock())
    assert all(r.status == StoryCodegenStatus.passed for r in results)
    # One fresh runner per story.
    assert len(made) == 2


@pytest.mark.asyncio
async def test_waves_persist_and_merge_like_sequential(session, tmp_path):
    """The merged results + per-story persistence are unchanged vs the sequential path:
    every story persisted, status map holds all ids, results in plan order."""
    items = [_dep_item("US-1"), _dep_item("US-2", depends_on=["US-1"]),
             _dep_item("US-3")]
    packs = {it.story_id: _pack(it) for it in items}
    statuses = itertools.cycle([StoryTestStatus.tests_failed, StoryTestStatus.ok])

    def run(module_dir, target, **k):
        return _result(next(statuses))

    results = await run_story_plan(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, now=_clock())
    assert [r.story_id for r in results] == ["US-1", "US-2", "US-3"]
    m = get_status_map(session, "ws1")
    assert set(m) == {"US-1", "US-2", "US-3"}
    for sid in ("US-1", "US-2", "US-3"):
        assert get_story_record(session, "ws1", sid)["status"] == "passed"


# --------------------------------------------------------------------------- #
# Repeat-until-done OUTER loop + pass-with-deferred + pooled budget            #
# --------------------------------------------------------------------------- #
def _story_id_from_target(target):
    """Recover the story id from a targeted test class name `PostUS-NTest`."""
    return target.replace("Post", "").replace("Test", "")


def _per_story_run_tests(red_passes_by_story):
    """A run_tests stub keyed on the targeted story id. `red_passes_by_story` maps a
    story id -> how many GREEN passes still need to RED before it goes green. Every call
    consumes one: while the story's remaining-red count > 0 it returns tests_failed (and
    decrements); at 0 it returns ok. A story absent from the map is green immediately."""
    state = dict(red_passes_by_story)
    calls = {"by_story": {}}

    def run(module_dir, target, **k):
        sid = _story_id_from_target(target)
        calls["by_story"][sid] = calls["by_story"].get(sid, 0) + 1
        remaining = state.get(sid, 0)
        if remaining > 0:
            state[sid] = remaining - 1
            return _result(StoryTestStatus.tests_failed)
        return _result(StoryTestStatus.ok)

    run.calls = calls
    return run


@pytest.mark.asyncio
async def test_until_done_all_pass_single_pass(session, tmp_path):
    """Happy path: every story passes on pass 1, so the loop runs exactly ONE pass."""
    items = [_dep_item("US-1"), _dep_item("US-2")]
    packs = {it.story_id: _pack(it) for it in items}
    passes = {"count": 0}
    iters: dict[str, object] = {}

    def run(module_dir, target, **k):
        sid = _story_id_from_target(target)
        if sid not in iters:
            iters[sid] = iter([StoryTestStatus.tests_failed, StoryTestStatus.ok])
        return _result(next(iters[sid]))

    def on_pass(failed):
        passes["count"] += 1

    results = await run_story_plan_until_done(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, now=_clock(), on_pass=on_pass)
    assert {r.story_id: r.status for r in results} == {
        "US-1": StoryCodegenStatus.passed, "US-2": StoryCodegenStatus.passed}
    assert passes["count"] == 1  # no retry passes


@pytest.mark.asyncio
async def test_until_done_failing_then_passing_story_reruns_only_it(session, tmp_path):
    """US-2 fails pass 1 but passes pass 2; US-1 passes pass 1. The loop re-runs ONLY
    US-2 on pass 2 (US-1 is accepted and not re-touched) and US-2 ends accepted."""
    items = [_dep_item("US-1"), _dep_item("US-2")]
    packs = {it.story_id: _pack(it) for it in items}
    # Per-story: each gen-impl pass triggers one run_tests (after the red baseline).
    # US-1 goes green immediately. US-2 stays red through its whole FIRST run_story
    # (baseline + impl + repairs all red) so pass 1 -> failed, then green on pass 2.
    seq = {
        "US-1": iter([StoryTestStatus.tests_failed, StoryTestStatus.ok,
                      StoryTestStatus.ok]),
        # pass1: red baseline + impl-red + repair-red(x2) -> failed
        # pass2: red baseline + impl-GREEN
        "US-2": iter([StoryTestStatus.tests_failed, StoryTestStatus.tests_failed,
                      StoryTestStatus.tests_failed, StoryTestStatus.tests_failed,
                      StoryTestStatus.tests_failed, StoryTestStatus.tests_failed,
                      StoryTestStatus.tests_failed, StoryTestStatus.ok]),
    }
    reran: dict[str, int] = {}

    def context_pack_for(it):
        reran[it.story_id] = reran.get(it.story_id, 0) + 1
        return packs[it.story_id]

    def run(module_dir, target, **k):
        sid = _story_id_from_target(target)
        return _result(next(seq[sid]))

    results = await run_story_plan_until_done(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=context_pack_for, runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, repair_max_attempts=2, now=_clock())
    by = {r.story_id: r.status for r in results}
    assert by["US-1"] == StoryCodegenStatus.passed
    assert by["US-2"] == StoryCodegenStatus.passed
    # US-1 built once; US-2 re-run on pass 2 -> its context_pack_for called twice.
    assert reran["US-1"] == 1
    assert reran["US-2"] == 2
    # Final-result ordering preserved (plan order).
    assert [r.story_id for r in results] == ["US-1", "US-2"]


@pytest.mark.asyncio
async def test_until_done_permanent_failure_becomes_deferred_and_terminates(
        session, tmp_path):
    """A story that NEVER goes green is marked `deferred` after BUILD_MAX_STORY_ATTEMPTS
    passes, the loop TERMINATES (bounded pass count, no infinite loop), and the other
    story is unaffected (passes pass 1, never re-run)."""
    items = [_dep_item("US-1"), _dep_item("US-2")]
    packs = {it.story_id: _pack(it) for it in items}
    pass_count = {"n": 0}
    built: dict[str, int] = {}

    def context_pack_for(it):
        built[it.story_id] = built.get(it.story_id, 0) + 1
        return packs[it.story_id]

    def run(module_dir, target, **k):
        sid = _story_id_from_target(target)
        if sid == "US-1":
            # red baseline then green
            it = run._g.setdefault(
                sid, iter([StoryTestStatus.tests_failed, StoryTestStatus.ok]))
            try:
                return _result(next(it))
            except StopIteration:
                return _result(StoryTestStatus.ok)
        # US-2 is ALWAYS red.
        return _result(StoryTestStatus.tests_failed)
    run._g = {}

    def on_pass(failed):
        pass_count["n"] += 1

    results = await run_story_plan_until_done(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=context_pack_for, runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, repair_max_attempts=0, max_story_attempts=3, now=_clock(),
        on_pass=on_pass)
    by = {r.story_id: r.status for r in results}
    assert by["US-1"] == StoryCodegenStatus.passed
    assert by["US-2"] == StoryCodegenStatus.deferred  # exhausted, not a hard error
    # Bounded: never more than BUILD_MAX_STORY_ATTEMPTS passes (terminates — no
    # infinite loop). The exact count may be smaller (no-progress can stop it earlier).
    assert pass_count["n"] <= 3
    assert pass_count["n"] >= 1
    # US-1 built exactly once (accepted on pass 1; NOT re-run on US-2's retries).
    assert built["US-1"] == 1
    # US-2 re-run at least once (the loop did retry the failing story).
    assert built["US-2"] >= 2
    # Deferred is DURABLE and NOT in the accepted set.
    rec = get_story_record(session, "ws1", "US-2")
    assert rec["status"] == "deferred"


@pytest.mark.asyncio
async def test_until_done_no_progress_pass_stops_the_loop(session, tmp_path):
    """If a retry pass yields NO newly-accepted story (no progress), the loop stops even
    though attempts remain — and the stuck story is deferred. Pass count is bounded by
    no-progress, not by exhausting the full attempt cap."""
    items = [_dep_item("US-1")]
    packs = {it.story_id: _pack(it) for it in items}
    pass_count = {"n": 0}

    def run(module_dir, target, **k):
        return _result(StoryTestStatus.tests_failed)  # always red

    def on_pass(failed):
        pass_count["n"] += 1

    results = await run_story_plan_until_done(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, repair_max_attempts=0, max_story_attempts=5, now=_clock(),
        on_pass=on_pass)
    assert results[0].status == StoryCodegenStatus.deferred
    # No-progress: pass 1 built nothing new, so the loop stopped after ~2 passes (the
    # first pass + one confirming no-progress pass) — well under the attempt cap of 5.
    assert pass_count["n"] <= 2


@pytest.mark.asyncio
async def test_until_done_pool_exhaustion_stops_new_attempts(session, tmp_path):
    """When the pooled token budget is exhausted, the loop stops spawning NEW retry
    passes (no runaway) and the still-failing story is deferred — even though attempts
    remained. Each pass burns tokens on the shared FakeRunner-driven gen seams."""
    items = [_dep_item("US-1")]
    packs = {it.story_id: _pack(it) for it in items}
    pass_count = {"n": 0}

    async def gen_impl(**kwargs):
        # Burn a big chunk of the pool every impl pass.
        kwargs["runner"].token_usage["output"] += 400
        return _impl_patch(story_id=kwargs["item"].story_id,
                           cobol_refs=tuple(kwargs["item"].cobol_refs))

    def run(module_dir, target, **k):
        return _result(StoryTestStatus.tests_failed)  # always red

    def on_pass(failed):
        pass_count["n"] += 1

    # Pass 1 burns 400 tokens; the pool (300) is then exhausted, so the outer loop must
    # stop spawning NEW attempts BEFORE pass 2. Per-story cap kept generous so the
    # per-story gate isn't what stops it — the POOL is.
    build_budget = BuildBudget(max_pool_tokens=300, per_story_max_tokens=1_000_000)
    results = await run_story_plan_until_done(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=gen_impl,
        run_tests=run, repair_max_attempts=0, max_story_attempts=10,
        build_budget=build_budget, now=_clock(), on_pass=on_pass)
    assert results[0].status == StoryCodegenStatus.deferred
    # The pool exhausted after the first pass, so NO runaway: only the single pass ran.
    assert pass_count["n"] == 1


@pytest.mark.asyncio
async def test_until_done_threads_per_story_cap_into_run_story(session, tmp_path):
    """The pooled budget's retained per-story cap is threaded into each story's run so a
    single story can't exceed it. Here a tiny per-story cap stops the repair loop early
    (attempts < repair_max_attempts + 1) and the story ends failed/deferred — proving
    the cap reached run_story."""
    items = [_dep_item("US-1")]
    packs = {it.story_id: _pack(it) for it in items}

    async def gen_impl(**kwargs):
        kwargs["runner"].token_usage["output"] += 1000  # over the 500 per-story cap
        return _impl_patch(story_id=kwargs["item"].story_id,
                           cobol_refs=tuple(kwargs["item"].cobol_refs))

    def run(module_dir, target, **k):
        return _result(StoryTestStatus.tests_failed)  # always red

    captured: list[int] = []
    orig = StoryBudget.exceeded

    def spy_exceeded(self, *, tokens_used, wall_s):
        captured.append(self.max_tokens)
        return orig(self, tokens_used=tokens_used, wall_s=wall_s)

    # Generous pool so it's the PER-STORY cap (500), not the pool, that bites.
    build_budget = BuildBudget(max_pool_tokens=10_000_000, per_story_max_tokens=500,
                               per_story_repair_attempts=5)
    import unittest.mock as _mock
    with _mock.patch.object(StoryBudget, "exceeded", spy_exceeded):
        results = await run_story_plan_until_done(
            items, session=session, workspace_id="ws1", module_dir=tmp_path,
            context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
            gen_tests=_make_gen_tests(), gen_impl=gen_impl, run_tests=run,
            repair_max_attempts=5, max_story_attempts=1,
            build_budget=build_budget, now=_clock())
    # run_story consulted a StoryBudget carrying the retained per-story cap (500).
    assert 500 in captured
    # Single pass, attempt cap of 1 -> deferred (never accepted, exhausted attempts).
    assert results[0].status == StoryCodegenStatus.deferred


@pytest.mark.asyncio
async def test_until_done_already_accepted_not_in_failed_set(session, tmp_path):
    """generated-unverified (accepted-but-unverified) stories are NOT re-run by the outer
    loop — they're accepted, so a toolchain-absent run converges in one pass."""
    items = [_dep_item("US-1")]
    packs = {it.story_id: _pack(it) for it in items}
    pass_count = {"n": 0}

    def run(module_dir, target, **k):
        return _result(StoryTestStatus.toolchain_unavailable)

    def on_pass(failed):
        pass_count["n"] += 1

    results = await run_story_plan_until_done(
        items, session=session, workspace_id="ws1", module_dir=tmp_path,
        context_pack_for=lambda it: packs[it.story_id], runner=FakeRunner(),
        gen_tests=_make_gen_tests(), gen_impl=_make_gen_impl(),
        run_tests=run, now=_clock(), on_pass=on_pass)
    assert results[0].status == StoryCodegenStatus.generated_unverified
    assert pass_count["n"] == 1  # accepted -> no retry pass
