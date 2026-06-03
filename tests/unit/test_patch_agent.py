"""Task 4: Test-First Patch Agent — per-story, bounded analogue of generate_slice.

These tests inject a STUB AgentRunner (no live LLM). They assert: schema shape
(story_id / acceptance_criteria_ids / rationale present, files-only, no shell),
kind filtering (tests->test, impl->main), the AC-citation instruction appears in
the assembled system/prompt, empty-{} -> ValueError, and timeout -> ValueError.
"""
from __future__ import annotations

import asyncio

import pytest

from cobol_modernizer.codegen.patch_agent import (
    DEFAULT_STORY_TIMEOUT_S,
    PATCH_SCHEMA,
    STORY_IMPL_SYSTEM,
    STORY_TESTS_SYSTEM,
    StoryPatch,
    generate_story_implementation,
    generate_story_tests,
    story_codegen_attempts,
    story_codegen_escalate,
)
from cobol_modernizer.codegen.schema import GeneratedFile
from cobol_modernizer.codegen.story_context import StoryContextPack
from cobol_modernizer.codegen.story_plan import StoryCodegenItem


class FakeRunner:
    """Foundation-style fake AgentRunner returning one canned structured payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict] = []

    async def run_structured(self, **kw):
        self.calls.append(kw)
        return self.payload


class HangingRunner:
    def __init__(self):
        self.calls: list[dict] = []

    async def run_structured(self, **kw):
        self.calls.append(kw)
        await asyncio.sleep(60)
        return {"files": []}


class HangThenOkRunner:
    """Hangs (forcing a timeout) on the first call, then returns a real payload on
    the next — exercises run_batched_result's escalated retry on a timeout."""

    def __init__(self, payload, *, hang_calls=1):
        self.payload = payload
        self.hang_calls = hang_calls
        self.calls: list[dict] = []

    async def run_structured(self, **kw):
        self.calls.append(kw)
        if len(self.calls) <= self.hang_calls:
            await asyncio.sleep(60)
        return self.payload


def _item() -> StoryCodegenItem:
    return StoryCodegenItem(
        story_id="US-1",
        bounded_context="Posting",
        service_name="PostingService",
        acceptance_criteria_ids=["AC-1", "AC-2"],
        cobol_refs=["CBTRN02C.2000-POST"],
    )


def _pack() -> StoryContextPack:
    return StoryContextPack(
        story_id="US-1",
        story_title="Post a transaction",
        story_narrative="As a teller I post a transaction so balances update.",
        acceptance_criteria=["valid transaction updates balance", "overdraft rejected"],
        aggregate_name="Account",
        invariants=["balance >= overdraft_limit"],
        methods=["post(amount)"],
        service_name="PostingService",
    )


_MIXED = {
    "files": [
        {
            "path": "src/test/java/com/x/PostingServiceTest.java",
            "kind": "test",
            "content": "// AC-1 class PostingServiceTest {}",
            "evidence": ["CBTRN02C.2000-POST"],
            "story_id": "US-1",
            "acceptance_criteria_ids": ["AC-1"],
            "rationale": "pin balance update",
        },
        {
            "path": "src/main/java/com/x/PostingService.java",
            "kind": "main",
            "content": "class PostingService {}",
            "evidence": ["CBTRN02C.2000-POST"],
            "story_id": "US-1",
            "acceptance_criteria_ids": ["AC-1"],
            "rationale": "minimal impl",
        },
    ]
}


# -- schema shape -----------------------------------------------------------

def test_patch_schema_is_files_only_no_shell():
    props = PATCH_SCHEMA["properties"]
    assert list(props.keys()) == ["files"]  # no shell/command field
    item = props["files"]["items"]["properties"]
    # reuses CODEGEN_SCHEMA shape ...
    for base in ("path", "kind", "content", "evidence"):
        assert base in item
    # ... extended with the story fields
    for extra in ("story_id", "acceptance_criteria_ids", "rationale"):
        assert extra in item
    assert item["kind"]["enum"] == ["test", "main"]


# -- tests generation -------------------------------------------------------

async def test_generate_story_tests_filters_to_test_kind():
    runner = FakeRunner(_MIXED)
    patch = await generate_story_tests(
        runner=runner, item=_item(), context_pack=_pack(),
        project_index=["pom.xml"], model="m", max_turns=2, timeout_s=5.0)
    assert isinstance(patch, StoryPatch)
    assert patch.files and all(isinstance(f, GeneratedFile) for f in patch.files)
    assert all(f.kind == "test" for f in patch.files)
    assert len(patch.files) == 1


async def test_generate_story_tests_surfaces_rationale():
    runner = FakeRunner(_MIXED)
    patch = await generate_story_tests(
        runner=runner, item=_item(), context_pack=_pack(),
        project_index=[], model="m", max_turns=2, timeout_s=5.0)
    # rationale comes from the kept (test) file's model output, scoped to that
    # kind so the dropped main file's rationale does not leak in
    assert "pin balance update" in patch.rationale
    assert "minimal impl" not in patch.rationale


async def test_generate_story_tests_surfaces_ac_citation_instruction():
    runner = FakeRunner(_MIXED)
    await generate_story_tests(
        runner=runner, item=_item(), context_pack=_pack(),
        project_index=["pom.xml"], model="m", max_turns=2, timeout_s=5.0)
    sent = (runner.calls[0]["system"] + runner.calls[0]["prompt"]).lower()
    assert "acceptance criterion" in sent or "acceptance criteria" in sent
    assert "cite" in sent
    # story + AC ids made available to the model
    assert "us-1" in sent and "ac-1" in sent and "ac-2" in sent


async def test_generate_story_tests_passes_project_index():
    runner = FakeRunner(_MIXED)
    await generate_story_tests(
        runner=runner, item=_item(), context_pack=_pack(),
        project_index=["pom.xml", "src/main/java/com/x/Account.java"],
        model="m", max_turns=2, timeout_s=5.0)
    assert "Account.java" in runner.calls[0]["prompt"]


async def test_generate_story_tests_runs_tool_free():
    runner = FakeRunner(_MIXED)
    await generate_story_tests(
        runner=runner, item=_item(), context_pack=_pack(),
        project_index=[], model="m", max_turns=2, timeout_s=5.0)
    assert runner.calls[0]["allowed_tools"] == []
    assert runner.calls[0]["server"] is None


async def test_generate_story_tests_empty_output_raises():
    runner = FakeRunner({})
    with pytest.raises(ValueError, match="no output|turn cap"):
        await generate_story_tests(
            runner=runner, item=_item(), context_pack=_pack(),
            project_index=[], model="m", max_turns=2, timeout_s=5.0)


async def test_generate_story_tests_times_out():
    # attempts=1 keeps this single-shot: one timed-out call -> one ValueError.
    runner = HangingRunner()
    with pytest.raises(ValueError, match="timeout|timed out"):
        await generate_story_tests(
            runner=runner, item=_item(), context_pack=_pack(),
            project_index=[], model="m", max_turns=2, timeout_s=0.01, attempts=1)
    assert len(runner.calls) == 1


async def test_generate_story_tests_retries_on_timeout_then_succeeds():
    """A timeout on attempt 1 is retryable: with attempts=2 the escalated retry
    succeeds, so the call returns rather than raising. TWO runner calls are made."""
    runner = HangThenOkRunner(_MIXED, hang_calls=1)
    patch = await generate_story_tests(
        runner=runner, item=_item(), context_pack=_pack(),
        project_index=[], model="m", max_turns=2, timeout_s=0.05, attempts=2)
    assert isinstance(patch, StoryPatch)
    assert all(f.kind == "test" for f in patch.files)
    assert len(runner.calls) == 2  # attempt 1 (timed out) + escalated retry (ok)


async def test_generate_story_tests_default_attempts_is_two():
    assert story_codegen_attempts() == 2
    assert story_codegen_escalate() is True


async def test_default_story_timeout_is_120():
    assert DEFAULT_STORY_TIMEOUT_S == 120.0


# -- implementation generation ----------------------------------------------

async def test_generate_story_implementation_filters_to_main_kind():
    runner = FakeRunner(_MIXED)
    failing = [GeneratedFile(
        path="src/test/java/com/x/PostingServiceTest.java", kind="test",
        content="// AC-1", evidence=["CBTRN02C.2000-POST"])]
    patch = await generate_story_implementation(
        runner=runner, item=_item(), context_pack=_pack(),
        failing_tests=failing, existing_java=[], model="m", max_turns=2,
        timeout_s=5.0)
    assert isinstance(patch, StoryPatch)
    assert patch.files and all(f.kind == "main" for f in patch.files)
    assert len(patch.files) == 1
    assert "minimal impl" in patch.rationale  # surfaced from the kept main file


async def test_generate_story_implementation_inlines_failing_tests():
    runner = FakeRunner(_MIXED)
    failing = [GeneratedFile(
        path="src/test/java/com/x/PostingServiceTest.java", kind="test",
        content="assertThrows(Overdraft.class, ...)", evidence=[])]
    await generate_story_implementation(
        runner=runner, item=_item(), context_pack=_pack(),
        failing_tests=failing, existing_java=[], model="m", max_turns=2,
        timeout_s=5.0)
    prompt = runner.calls[0]["prompt"]
    assert "assertThrows(Overdraft.class" in prompt


async def test_generate_story_implementation_inlines_existing_java():
    runner = FakeRunner(_MIXED)
    existing = [GeneratedFile(
        path="src/main/java/com/x/Account.java", kind="main",
        content="class Account { long balance; }", evidence=[])]
    await generate_story_implementation(
        runner=runner, item=_item(), context_pack=_pack(),
        failing_tests=[], existing_java=existing, model="m", max_turns=2,
        timeout_s=5.0)
    prompt = runner.calls[0]["prompt"]
    assert "class Account { long balance; }" in prompt


async def test_generate_story_implementation_grounded_only_no_invention():
    """The impl system prompt must forbid inventing behavior absent from the pack."""
    assert "invent" in STORY_IMPL_SYSTEM.lower()


async def test_generate_story_implementation_folds_in_repair_feedback():
    """On a repair pass the failing gate + build-log excerpt + touched files are
    threaded into the impl prompt (mirrors repair_loop's feedback shape)."""
    runner = FakeRunner(_MIXED)
    await generate_story_implementation(
        runner=runner, item=_item(), context_pack=_pack(),
        failing_tests=[], existing_java=[], model="m", max_turns=2, timeout_s=5.0,
        repair_feedback={"failing_gate": "tests-failed",
                         "log_excerpt": "expected <true> but was <false>",
                         "touched_files": ["src/main/java/com/x/Account.java"]})
    prompt = runner.calls[0]["prompt"]
    assert "tests-failed" in prompt
    assert "expected <true> but was <false>" in prompt
    assert "src/main/java/com/x/Account.java" in prompt


async def test_generate_story_implementation_no_repair_section_on_first_pass():
    """Without repair feedback the prompt carries no repair section (first pass)."""
    runner = FakeRunner(_MIXED)
    await generate_story_implementation(
        runner=runner, item=_item(), context_pack=_pack(),
        failing_tests=[], existing_java=[], model="m", max_turns=2, timeout_s=5.0)
    assert "Previous attempt failed gate" not in runner.calls[0]["prompt"]


async def test_generate_story_implementation_empty_output_raises():
    runner = FakeRunner({})
    with pytest.raises(ValueError, match="no output|turn cap"):
        await generate_story_implementation(
            runner=runner, item=_item(), context_pack=_pack(),
            failing_tests=[], existing_java=[], model="m", max_turns=2,
            timeout_s=5.0)


async def test_generate_story_implementation_times_out():
    runner = HangingRunner()
    with pytest.raises(ValueError, match="timeout|timed out"):
        await generate_story_implementation(
            runner=runner, item=_item(), context_pack=_pack(),
            failing_tests=[], existing_java=[], model="m", max_turns=2,
            timeout_s=0.01, attempts=1)
    assert len(runner.calls) == 1


async def test_generate_story_implementation_retries_on_timeout_then_succeeds():
    runner = HangThenOkRunner(_MIXED, hang_calls=1)
    patch = await generate_story_implementation(
        runner=runner, item=_item(), context_pack=_pack(),
        failing_tests=[], existing_java=[], model="m", max_turns=2,
        timeout_s=0.05, attempts=2)
    assert isinstance(patch, StoryPatch)
    assert all(f.kind == "main" for f in patch.files)
    assert len(runner.calls) == 2


# -- system prompts ---------------------------------------------------------

def test_tests_system_demands_junit5_and_ac_citation():
    s = STORY_TESTS_SYSTEM.lower()
    assert "junit" in s
    assert "kind='test'" in s
    assert "cite" in s and "acceptance" in s


def test_impl_system_emits_main_only_and_satisfies_failing_tests():
    s = STORY_IMPL_SYSTEM.lower()
    assert "kind='main'" in s
    # emits production code ONLY (must not also write/modify tests) ...
    assert "do not emit or modify tests" in s
    # ... whose explicit job is to make the failing tests pass
    assert "failing tests pass" in s
