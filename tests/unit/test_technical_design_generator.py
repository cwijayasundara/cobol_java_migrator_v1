import asyncio

from cobol_modernizer.technical_design.generator import (
    TECHNICAL_DESIGN_SCHEMA,
    TECHNICAL_DESIGN_SYSTEM,
    build_technical_design_prompt,
    fallback_technical_design_payload,
    generate_technical_design_payload,
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
