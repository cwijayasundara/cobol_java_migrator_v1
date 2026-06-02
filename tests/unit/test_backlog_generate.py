import asyncio

from cobol_modernizer.backlog.generator import (
    BACKLOG_SCHEMA,
    BACKLOG_SYSTEM,
    build_backlog_prompt,
    generate_backlog_payload,
)


class FakeRunner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def run_structured(self, *, system, prompt, server, allowed_tools, model,
                             max_turns, schema, label):
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        return self.payload


def test_build_backlog_prompt_includes_brd_and_refs():
    prompt = build_backlog_prompt(
        brd_sections=[{"title": "Functional", "requirements": [{"id": "FR-1", "text": "Post tx"}]}],
        known_refs=["CBPOST1M"], known_requirement_ids=["FR-1"])
    assert "FR-1" in prompt
    assert "CBPOST1M" in prompt


def test_generate_backlog_payload_returns_raw_dict():
    runner = FakeRunner({"epics": [], "stories": []})
    raw = asyncio.run(generate_backlog_payload(
        runner=runner, model="m", timeout_s=5.0,
        brd_sections=[{"title": "t", "requirements": [{"id": "FR-1", "text": "x"}]}],
        known_refs=["CBPOST1M"], known_requirement_ids=["FR-1"]))
    assert raw == {"epics": [], "stories": []}
    assert "FR-1" in runner.calls[0]["prompt"]
    assert runner.calls[0]["schema"] is BACKLOG_SCHEMA
    assert runner.calls[0]["system"] is BACKLOG_SYSTEM
