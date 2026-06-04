from __future__ import annotations

from cobol_modernizer.codegen.schema import GeneratedFile
from cobol_modernizer.codegen.story_context import StoryContextPack
from cobol_modernizer.codegen.story_plan import StoryCodegenItem
from cobol_modernizer.codegen.story_quality import evaluate_story_quality
from cobol_modernizer.codegen.test_runner import StoryTestStatus


def _item() -> StoryCodegenItem:
    return StoryCodegenItem(
        story_id="US-7",
        bounded_context="Posting",
        service_name="posting-service",
        acceptance_criteria_ids=["AC-1"],
        cobol_refs=["COTRN02C.cbl#L10-L20"],
    )


def test_story_quality_passes_when_required_signals_are_present():
    pack = StoryContextPack(
        story_id="US-7",
        service_name="posting-service",
        package_lines=["com.example.posting.application"],
        behavior_model={"io_operations": ["WRITE TRANSACT-REC"]},
    )
    files = [
        GeneratedFile(
            path="src/test/java/com/example/posting/api/US7AcceptanceTest.java",
            kind="test",
            content="// US-7 AC-1 TRANSACT",
            evidence=["US-7", "AC-1"],
        ),
        GeneratedFile(
            path="src/main/java/com/example/posting/application/PostingService.java",
            kind="main",
            content="// story US-7 COTRN02C.cbl#L10-L20 writes transact",
            evidence=["US-7", "COTRN02C.cbl#L10-L20"],
        ),
    ]

    gate = evaluate_story_quality(
        item=_item(),
        context_pack=pack,
        test_status=StoryTestStatus.ok,
        ac_missing=[],
        lineage_ok=True,
        test_files=[files[0]],
        impl_files=[files[1]],
        changed_files=[files[1].path],
    )

    assert gate.passed is True
    assert gate.score == 1.0
    assert gate.failures == []


def test_story_quality_fails_missing_behavior_and_package_scope():
    pack = StoryContextPack(
        story_id="US-7",
        package_lines=["com.example.posting.application"],
        behavior_model={"io_operations": ["WRITE TRANSACT-REC"]},
    )
    impl = GeneratedFile(
        path="src/main/java/com/example/statement/StatementService.java",
        kind="main",
        content="// story US-7 COTRN02C.cbl#L10-L20",
        evidence=["US-7", "COTRN02C.cbl#L10-L20"],
    )

    gate = evaluate_story_quality(
        item=_item(),
        context_pack=pack,
        test_status=StoryTestStatus.ok,
        ac_missing=[],
        lineage_ok=True,
        test_files=[],
        impl_files=[impl],
        changed_files=[impl.path],
    )

    assert gate.passed is False
    assert "changed production files are outside story package scope" in gate.failures
    assert "COBOL behavior-model signals are not represented in generated files" in gate.failures
