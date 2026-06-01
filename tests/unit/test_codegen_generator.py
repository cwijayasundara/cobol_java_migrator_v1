import pytest
from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject
from cobol_modernizer.codegen.generator import generate_slice, CODEGEN_SCHEMA


class FakeRunner:
    """Foundation-style fake AgentRunner returning canned structured output."""
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def run_structured(self, **kw):
        self.calls.append(kw)
        return self.payload


PAYLOAD = {"files": [
    {"path": "src/test/java/com/cobolmodernizer/posting/PostingServiceTest.java",
     "kind": "test", "content": "class PostingServiceTest {}",
     "evidence": ["CBTRN02C.2000-POST-TRANSACTION"]},
    {"path": "src/main/java/com/cobolmodernizer/posting/service/PostingService.java",
     "kind": "main", "content": "class PostingService {}",
     "evidence": ["CBTRN02C.2800-UPDATE-ACCOUNT-REC"]},
]}


async def test_generator_emits_tests_before_main_and_evidence_map():
    runner = FakeRunner(PAYLOAD)
    project = await generate_slice(
        runner=runner, server=None, model="claude-sonnet-4-6",
        brd_json='{"sections":[]}', golden_summary="after_acctfile diff",
        allowed_tools=["mcp__graph__get_source_slice"])
    assert isinstance(project, GeneratedProject)
    # TDD invariant: a test file precedes its production file
    kinds = [f.kind for f in project.files]
    assert kinds.index("test") < kinds.index("main")
    assert project.evidence_map["CBTRN02C.2800-UPDATE-ACCOUNT-REC"]


async def test_generator_rejects_run_with_no_test_file():
    runner = FakeRunner({"files": [
        {"path": "X.java", "kind": "main", "content": "x", "evidence": ["CBTRN02C"]}]})
    with pytest.raises(ValueError, match="no failing test"):
        await generate_slice(runner=runner, server=None, model="m",
                             brd_json="{}", golden_summary="", allowed_tools=[])


async def test_generator_reports_empty_output_distinctly_from_tdd_violation():
    # runner returned {} (agent hit the turn cap / errored) -> a clear operational
    # message that names the cap, NOT the misleading "TDD violated".
    runner = FakeRunner({})
    with pytest.raises(ValueError, match="no output.*turn cap"):
        await generate_slice(runner=runner, server=None, model="m", brd_json="{}",
                             golden_summary="", allowed_tools=[], max_turns=12)


def test_codegen_schema_requires_files():
    assert "files" in CODEGEN_SCHEMA["required"]
