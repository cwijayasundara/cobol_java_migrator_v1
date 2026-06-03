import asyncio

from cobol_modernizer.technical_design.generator import (
    TECHNICAL_DESIGN_SCHEMA,
    TECHNICAL_DESIGN_SYSTEM,
    build_service_prompt,
    build_technical_design_prompt,
    fallback_technical_design_payload,
    generate_service_for_context,
    generate_technical_design_payload,
    generate_technical_design_result,
    parse_technical_design_payload,
)


def test_prompt_includes_ddd_backlog_and_seams():
    prompt = build_technical_design_prompt(
        ddd_json='{"contexts":[{"name":"Posting"}]}',
        backlog_json='{"stories":[{"id":"US-1"}]}',
        seam_waves_json='[["CBPOST1M"]]',
        graph_summary={"programs": ["CBPOST1M"]})
    assert "Posting" in prompt
    assert "US-1" in prompt
    assert "CBPOST1M" in prompt


def test_parse_drops_ungrounded_story_ids_contexts_and_refs():
    raw = {"services": [{
        "name": "posting-service", "bounded_context": "Posting", "deployment": "module",
        "story_ids": ["US-1", "GHOST"],
        "api_contracts": [{"name": "post", "method": "POST", "path": "/p"}],
        "persistence": [{"resource": "ACCTFILE", "access_pattern": "legacy-mimic"}],
        "evidence_refs": ["CBPOST1M", "GHOST"],
    }, {
        "name": "ghost-service", "bounded_context": "Unknown", "deployment": "module",
        "story_ids": [], "evidence_refs": [],
    }]}
    design = parse_technical_design_payload(
        raw, repo_slug="carddemo-mini", known_refs={"CBPOST1M"},
        known_story_ids={"US-1"}, known_contexts={"Posting"})
    assert len(design.services) == 1  # ghost-service dropped (unknown context)
    svc = design.services[0]
    assert svc.story_ids == ["US-1"]
    assert svc.evidence_refs == ["CBPOST1M"]
    assert svc.persistence[0].resource == "ACCTFILE"


class FakeRunner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def run_structured(self, **kw):
        self.calls.append(kw)
        return self.payload


def test_generate_returns_raw_payload():
    runner = FakeRunner({"services": []})
    raw = asyncio.run(generate_technical_design_payload(
        runner=runner, model="m", timeout_s=5.0, ddd_json="{}", backlog_json="{}",
        seam_waves_json="[]", graph_summary={}))
    assert raw == {"services": []}
    assert runner.calls[0]["schema"] is TECHNICAL_DESIGN_SCHEMA
    assert runner.calls[0]["system"] is TECHNICAL_DESIGN_SYSTEM
    assert runner.calls[0]["max_turns"] == 6  # default headroom above run_batched's 2


def test_generate_forwards_custom_max_turns():
    runner = FakeRunner({"services": []})
    asyncio.run(generate_technical_design_payload(
        runner=runner, model="m", timeout_s=5.0, ddd_json="{}", backlog_json="{}",
        seam_waves_json="[]", graph_summary={}, max_turns=9))
    assert runner.calls[0]["max_turns"] == 9


def test_parse_coerces_out_of_enum_literals():
    detailed_pattern = "read-by-key then rewrite-by-key inside a transaction"
    raw = {"services": [{
        "name": "posting-service", "bounded_context": "Posting",
        "deployment": "microservice-v2",
        "persistence": [{"resource": "X", "access_pattern": detailed_pattern}],
        "integrations": [{"name": "n", "style": "weird", "target": "t"}],
    }]}
    design = parse_technical_design_payload(
        raw, repo_slug="r", known_refs=set(), known_story_ids=set(),
        known_contexts={"Posting"})
    svc = design.services[0]
    assert svc.deployment == "module"
    assert svc.persistence[0].access_pattern == "legacy-mimic"
    assert detailed_pattern in svc.persistence[0].details
    assert svc.integrations[0].style == "sync"


def test_parse_empty_payload_safe():
    design = parse_technical_design_payload(
        {}, repo_slug="r", known_refs=set(), known_story_ids=set(), known_contexts=set())
    assert design.services == []


def test_fallback_payload_builds_one_service_per_context_from_grounded_inputs():
    raw = fallback_technical_design_payload(
        contexts=[{
            "name": "Posting",
            "member_programs": ["CBPOST1M", "GHOST"],
            "owned_resources": ["ACCTFILE"],
            "depends_on": [{"target": "Accounts", "style": "async"}],
        }],
        stories=[{"id": "US-1", "context": "Posting", "evidence_refs": ["CBPOST1M"]}],
        seam_waves=[["CBPOST1M"]],
        known_refs={"CBPOST1M"},
    )
    svc = raw["services"][0]
    assert svc["name"] == "posting-service"
    assert svc["bounded_context"] == "Posting"
    assert svc["story_ids"] == ["US-1"]
    assert svc["evidence_refs"] == ["CBPOST1M"]
    assert svc["persistence"][0]["owner_service"] == "posting-service"
    assert svc["integrations"][0]["style"] == "async"


class RecordingRunner:
    """Records each structured call's prompt so we can assert on inlined refs."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def run_structured(self, **kw):
        self.calls.append(kw)
        return self.payload


# --- Step 2: lossless relevance scoping (no [:200] truncation) ----------------


def test_service_prompt_inlines_all_relevant_refs_no_truncation():
    # A context citing >200 relevant refs must inline ALL of them — there is no
    # cap/truncation anywhere in the per-context generation path.
    refs = [f"CBREF{i:04d}" for i in range(250)]
    prompt = build_service_prompt(
        context={"name": "Posting", "member_programs": refs},
        backlog_json="{}", seam_waves_json="[]",
        relevant_refs=refs, known_story_ids=["US-1"])
    for ref in refs:
        assert ref in prompt
    assert len(refs) == 250


def test_decomposed_orchestrator_scopes_each_context_to_its_own_refs():
    runner = RecordingRunner({"services": [
        {"name": "x", "bounded_context": "X", "deployment": "module"}]})
    contexts = [
        {"name": "Posting", "member_programs": ["CBPOST1M"]},
        {"name": "Accounts", "member_programs": ["CBACCT1M"]},
    ]
    result = asyncio.run(generate_technical_design_result(
        runner=runner, model="m", timeout_s=5.0, mode="decomposed",
        contexts=contexts, stories=[{"id": "US-1"}], seam_waves=[],
        known_refs=["CBPOST1M", "CBACCT1M"], known_story_ids=["US-1"]))
    assert result.ok
    # one structured call per context, each prompt carries ONLY its own ref
    prompts = [c["prompt"] for c in runner.calls]
    posting = next(p for p in prompts if "Posting" in p)
    accounts = next(p for p in prompts if "Accounts" in p)
    assert "CBPOST1M" in posting and "CBACCT1M" not in posting
    assert "CBACCT1M" in accounts and "CBPOST1M" not in accounts
    # merged into the {services: [...]} shape the parser consumes
    assert len(result.payload["services"]) == 2


def test_per_context_call_failure_surfaces_typed_cause():
    class FailingRunner:
        calls = []

        async def run_structured(self, **kw):
            FailingRunner.calls.append(kw)
            return {}  # empty -> typed failure (turn cap / parse / api error)

    result = asyncio.run(generate_technical_design_result(
        runner=FailingRunner(), model="m", timeout_s=5.0, mode="decomposed",
        contexts=[{"name": "Posting", "member_programs": ["CBPOST1M"]}],
        stories=[], seam_waves=[], known_refs=["CBPOST1M"], known_story_ids=[]))
    assert not result.ok
    assert result.cause and "no output" in result.cause


def test_generate_service_for_context_returns_typed_result():
    runner = RecordingRunner({"services": [
        {"name": "posting-service", "bounded_context": "Posting", "deployment": "module"}]})
    res = asyncio.run(generate_service_for_context(
        runner=runner, model="m", timeout_s=5.0, max_turns=6,
        context={"name": "Posting", "member_programs": ["CBPOST1M"]},
        backlog_json="{}", seam_waves_json="[]",
        relevant_refs=["CBPOST1M"], known_story_ids=["US-1"]))
    assert res.ok
    assert res.payload["services"][0]["bounded_context"] == "Posting"


def test_oneshot_mode_uses_single_call():
    runner = RecordingRunner({"services": [
        {"name": "x", "bounded_context": "X", "deployment": "module"}]})
    result = asyncio.run(generate_technical_design_result(
        runner=runner, model="m", timeout_s=5.0, mode="oneshot",
        contexts=[{"name": "X"}, {"name": "Y"}], stories=[], seam_waves=[],
        known_refs=[], known_story_ids=[]))
    assert result.ok
    assert len(runner.calls) == 1  # single combined call, not per-context
