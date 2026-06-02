import asyncio

from cobol_modernizer.technical_design.generator import (
    TECHNICAL_DESIGN_SCHEMA,
    build_technical_design_prompt,
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
