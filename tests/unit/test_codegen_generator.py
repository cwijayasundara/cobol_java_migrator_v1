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


class SequencedRunner:
    """Returns a different canned payload per call (to drive the repair loop)."""
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def run_structured(self, **kw):
        self.calls.append(kw)
        idx = min(len(self.calls) - 1, len(self.payloads) - 1)
        return self.payloads[idx]


_MAIN_ONLY = {"files": [
    {"path": "src/main/java/com/x/PostingService.java", "kind": "main",
     "content": "class PostingService {}", "evidence": ["CBTRN02C.2800-UPDATE"]}]}
_TESTS_ONLY = {"files": [
    {"path": "src/test/java/com/x/PostingServiceTest.java", "kind": "test",
     "content": "class PostingServiceTest {}", "evidence": ["CBTRN02C.2000-POST"]}]}


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


async def test_generator_repairs_a_tests_less_generation():
    """A generation that emits code but no test must NOT throw away the work — the
    engine issues a focused 'emit the missing failing tests' call and merges them in,
    tests first. This is the exact failure that was hard-failing the build."""
    runner = SequencedRunner([_MAIN_ONLY, _TESTS_ONLY])
    project = await generate_slice(
        runner=runner, server=None, model="claude-haiku-4-5",
        brd_json='{"domain_design": {}}', golden_summary="", allowed_tools=[],
        repair_attempts=2)
    assert isinstance(project, GeneratedProject)
    assert len(runner.calls) == 2                      # main attempt + one repair
    kinds = [f.kind for f in project.files]
    assert "test" in kinds and "main" in kinds
    assert kinds.index("test") < kinds.index("main")   # tests first, post-merge


async def test_generator_repair_call_asks_only_for_tests():
    runner = SequencedRunner([_MAIN_ONLY, _TESTS_ONLY])
    await generate_slice(runner=runner, server=None, model="m",
                         brd_json="{}", golden_summary="", allowed_tools=[],
                         repair_attempts=1)
    repair = (runner.calls[1]["system"] + runner.calls[1]["prompt"]).lower()
    assert "test" in repair and "only" in repair


async def test_generator_raises_after_repair_attempts_exhausted():
    runner = SequencedRunner([_MAIN_ONLY])  # every call returns main-only
    with pytest.raises(ValueError, match="no failing test"):
        await generate_slice(runner=runner, server=None, model="m", brd_json="{}",
                             golden_summary="", allowed_tools=[], repair_attempts=2)
    assert len(runner.calls) == 3  # initial + 2 repair attempts, all tests-less


async def test_generator_treats_graph_as_last_resort():
    """The brief (BRD + DDD/OO design) is the primary source of truth; the live graph
    is only a fallback. The system prompt must say so, or the agent burns turns
    navigating the graph it doesn't need."""
    runner = FakeRunner(PAYLOAD)
    await generate_slice(runner=runner, server=None, model="m", brd_json="{}",
                         golden_summary="", allowed_tools=[])
    system = runner.calls[0]["system"].lower()
    assert "last resort" in system
    assert "domain design" in system


async def test_generator_inlines_source_pack_to_avoid_graph_exploration():
    """When the (small) slice source is handed in, the prompt must carry it verbatim
    and tell the agent it needs no graph exploration — that's what lets a tiny repo
    finish in a couple of turns instead of dozens of tool round-trips."""
    runner = FakeRunner(PAYLOAD)
    await generate_slice(
        runner=runner, server=None, model="claude-sonnet-4-6",
        brd_json="{}", golden_summary="", allowed_tools=[],
        source_pack="### CBTRN02C\n```cobol\nPROCEDURE DIVISION.\n```")
    prompt = runner.calls[0]["prompt"]
    assert "PROCEDURE DIVISION." in prompt          # source inlined verbatim
    assert "exploration" in prompt.lower()           # told it needn't explore


async def test_generator_directs_agent_to_assert_domain_design():
    """The brief now carries the DDD/OO domain design; the agent must be told to
    turn its aggregate invariants / api surface into the failing tests. Without this
    cue the cheap tier writes code and skips tests (the 'no failing test' failure)."""
    runner = FakeRunner(PAYLOAD)
    await generate_slice(
        runner=runner, server=None, model="claude-haiku-4-5",
        brd_json='{"domain_design": {"designs": []}}', golden_summary="",
        allowed_tools=[])
    sent = (runner.calls[0]["system"] + runner.calls[0]["prompt"]).lower()
    assert "domain design" in sent
    assert "invariant" in sent


async def test_generator_directs_agent_to_turn_acceptance_criteria_into_tests():
    runner = FakeRunner(PAYLOAD)
    await generate_slice(
        runner=runner,
        server=None,
        model="m",
        brd_json='{"backlog":{"stories":[{"id":"US-1","acceptance_criteria":[{"id":"AC-1","statement":"valid transaction updates balance"}]}]}}',
        golden_summary="",
        allowed_tools=[],
    )
    sent = (runner.calls[0]["system"] + runner.calls[0]["prompt"]).lower()
    assert "acceptance criteria" in sent
    assert "ac-1" in sent
    assert "valid transaction updates balance" in sent
