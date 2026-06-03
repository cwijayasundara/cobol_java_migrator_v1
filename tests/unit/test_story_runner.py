"""Unit tests for the story runner (Task 6). No live LLM / Maven / Neo4j — every
heavy dependency is injected: a fake AgentRunner, canned gen_tests/gen_impl
returning StoryPatch, a scripted run_tests returning StoryTestResult sequences, an
in-memory SQLite session, and a patched (incrementing) clock."""
from __future__ import annotations

import itertools

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cobol_modernizer.codegen.schema import GeneratedFile
from cobol_modernizer.codegen.story_context import build_story_context
from cobol_modernizer.codegen.patch_agent import StoryPatch
from cobol_modernizer.codegen.story_plan import StoryCodegenItem, StoryCodegenStatus
from cobol_modernizer.codegen.story_runner import run_story, run_story_plan
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
    assert max(a.version for a in arts) == 1
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
    assert max(art.version for art in arts) == 2


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
