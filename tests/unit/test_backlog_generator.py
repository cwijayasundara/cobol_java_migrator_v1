import asyncio
import json

import pytest

from cobol_modernizer.backlog.generator import (
    BACKLOG_SCHEMA,
    EPICS_SCHEMA,
    EPICS_SYSTEM,
    STORIES_SCHEMA,
    STORIES_SYSTEM,
    build_backlog_prompt,
    generate_epics,
    generate_stories_for_epic,
    parse_backlog_payload,
)
from cobol_modernizer.enrichment.base import EnrichmentResult
from cobol_modernizer.enrichment.refs import relevant_refs


class FakeRunner:
    """Records every run_structured call and returns a canned payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def run_structured(self, *, system, prompt, server, allowed_tools, model,
                             max_turns, schema, label):
        self.calls.append({
            "system": system, "prompt": prompt, "schema": schema,
            "model": model, "max_turns": max_turns, "label": label,
        })
        return self.payload


def test_parse_backlog_payload_drops_ungrounded_refs():
    raw = {
        "epics": [
            {
                "id": "EPIC-1",
                "title": "Posting",
                "outcome": "Apply transactions",
                "brd_requirement_ids": ["FR-1"],
                "story_ids": ["US-1"],
                "evidence_refs": ["CBPOST1M", "GHOST"],
            }
        ],
        "stories": [
            {
                "id": "US-1",
                "epic_id": "EPIC-1",
                "title": "Post valid transaction",
                "actor": "posting batch",
                "narrative": "As a posting batch I apply valid transactions.",
                "brd_requirement_ids": ["FR-1"],
                "acceptance_criteria": [
                    {
                        "id": "AC-1",
                        "statement": "Valid amount updates account balance.",
                        "evidence_refs": ["CBPOST1M.2100-POST-TRAN", "GHOST"],
                    }
                ],
                "evidence_refs": ["CBPOST1M.2100-POST-TRAN", "GHOST"],
            }
        ],
    }

    backlog = parse_backlog_payload(
        raw,
        repo_slug="carddemo-mini",
        known_refs={"CBPOST1M", "CBPOST1M.2100-POST-TRAN"},
        known_requirement_ids={"FR-1"},
    )

    assert backlog.epics[0].evidence_refs == ["CBPOST1M"]
    assert backlog.stories[0].evidence_refs == ["CBPOST1M.2100-POST-TRAN"]
    assert backlog.stories[0].acceptance_criteria[0].evidence_refs == ["CBPOST1M.2100-POST-TRAN"]


def test_parse_backlog_rejects_story_without_acceptance_criteria():
    raw = {
        "epics": [],
        "stories": [
            {
                "id": "US-1",
                "epic_id": "EPIC-1",
                "title": "No criteria",
                "actor": "user",
                "narrative": "As a user I need behavior.",
                "brd_requirement_ids": ["FR-1"],
                "acceptance_criteria": [],
                "evidence_refs": ["CBPOST1M"],
            }
        ],
    }

    with pytest.raises(ValueError, match="acceptance criteria"):
        parse_backlog_payload(
            raw,
            repo_slug="carddemo-mini",
            known_refs={"CBPOST1M"},
            known_requirement_ids={"FR-1"},
        )


def test_relevant_refs_scopes_prompt_to_cited_subset_not_whole_or_slice():
    # Full graph has 1000 refs; the BRD only cites a specific subset of 3.
    known_refs = [f"PGM{i}" for i in range(1000)]
    cited = ["PGM7", "PGM42", "PGM900"]
    sections = [{"title": "Functional",
                 "requirements": [{"id": "FR-1", "text": "x", "evidence_refs": cited}]}]

    relevant = relevant_refs(sections, known_refs)
    # Exactly the cited subset (relevance-only) — NOT the whole 1000, NOT a numeric slice.
    assert set(relevant) == set(cited)
    assert len(relevant) == 3

    prompt = build_backlog_prompt(brd_sections=sections, known_refs=relevant,
                                  known_requirement_ids=["FR-1"])
    # Only the cited refs appear in the evidence-refs block of the prompt.
    refs_block = prompt.split("Known graph evidence refs (cite only these)")[1]
    inlined = json.loads(refs_block.split("```json\n")[1].split("\n```")[0])
    assert set(inlined) == set(cited)
    # A non-cited ref must NOT be inlined (no whole-graph dump).
    assert "PGM500" not in inlined


def test_relevant_refs_inlines_all_500_cited_no_truncation():
    known_refs = [f"PGM{i}" for i in range(1000)]
    cited = [f"PGM{i}" for i in range(500)]  # BRD cites exactly 500 of them
    sections = [{"requirements": [{"id": "FR-1", "evidence_refs": cited}]}]

    relevant = relevant_refs(sections, known_refs)
    assert len(relevant) == 500
    assert set(relevant) == set(cited)

    prompt = build_backlog_prompt(brd_sections=sections, known_refs=relevant,
                                  known_requirement_ids=["FR-1"])
    refs_block = prompt.split("Known graph evidence refs (cite only these)")[1]
    inlined = json.loads(refs_block.split("```json\n")[1].split("\n```")[0])
    # All 500 inlined — no truncation, no [:N] cap.
    assert len(inlined) == 500
    assert set(inlined) == set(cited)


# ---------------------------------------------------------------------------
# Split schemas
# ---------------------------------------------------------------------------

def test_epics_schema_is_epics_only():
    assert EPICS_SCHEMA["required"] == ["epics"]
    assert "stories" not in EPICS_SCHEMA["properties"]
    epic_item = EPICS_SCHEMA["properties"]["epics"]["items"]
    # Same epic-object fields + required list as the legacy one-shot schema.
    legacy_epic = BACKLOG_SCHEMA["properties"]["epics"]["items"]
    assert epic_item["required"] == legacy_epic["required"]
    assert set(epic_item["properties"]) == set(legacy_epic["properties"])


def test_stories_schema_is_stories_only():
    assert STORIES_SCHEMA["required"] == ["stories"]
    assert "epics" not in STORIES_SCHEMA["properties"]
    story_item = STORIES_SCHEMA["properties"]["stories"]["items"]
    legacy_story = BACKLOG_SCHEMA["properties"]["stories"]["items"]
    # Same story-object fields + required list (incl. nested acceptance_criteria + epic_id).
    assert story_item["required"] == legacy_story["required"]
    assert set(story_item["properties"]) == set(legacy_story["properties"])
    assert "epic_id" in story_item["properties"]
    assert "acceptance_criteria" in story_item["properties"]


# ---------------------------------------------------------------------------
# generate_epics — single bounded call, epics schema, lossless relevant refs
# ---------------------------------------------------------------------------

def test_generate_epics_one_call_with_epics_schema():
    runner = FakeRunner({"epics": [{"id": "EPIC-1", "title": "T", "outcome": "O"}]})
    sections = [{"title": "Functional", "requirements": [{"id": "FR-1", "text": "x"}]}]
    refs = ["CBPOST1M", "CBACT01C"]

    result = asyncio.run(generate_epics(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        brd_sections=sections, relevant_refs=refs, known_requirement_ids=["FR-1"]))

    assert isinstance(result, EnrichmentResult)
    assert result.ok is True
    assert result.payload == {"epics": [{"id": "EPIC-1", "title": "T", "outcome": "O"}]}
    # Exactly ONE bounded call, with the EPICS schema (not the legacy combined one).
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["schema"] is EPICS_SCHEMA
    assert call["system"] is EPICS_SYSTEM
    assert call["max_turns"] == 5
    # Prompt asks ONLY for epics, inlines the (already-lossless) relevant refs.
    assert "FR-1" in call["prompt"]
    assert "CBPOST1M" in call["prompt"] and "CBACT01C" in call["prompt"]
    # Epics-only: the prompt explicitly suppresses story/AC generation.
    assert "EPIC layer only" in call["prompt"]
    assert "Do NOT emit user stories" in call["prompt"]


def test_generate_epics_passes_through_failure_cause():
    runner = FakeRunner({})  # empty payload => harness-swallowed failure
    result = asyncio.run(generate_epics(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        brd_sections=[{"requirements": [{"id": "FR-1"}]}],
        relevant_refs=["CBPOST1M"], known_requirement_ids=["FR-1"]))
    assert result.ok is False
    assert result.payload == {}
    assert result.cause is not None


# ---------------------------------------------------------------------------
# generate_stories_for_epic — single call, stories schema, scoped to ONE epic
# ---------------------------------------------------------------------------

def test_generate_stories_for_epic_one_call_with_stories_schema():
    runner = FakeRunner({"stories": [{
        "id": "US-1", "epic_id": "EPIC-1", "title": "T", "actor": "a",
        "narrative": "n", "acceptance_criteria": [{"id": "AC-1", "statement": "s"}]}]})
    epic = {"id": "EPIC-1", "title": "Posting", "outcome": "Apply transactions"}
    sections = [{"title": "Functional",
                 "requirements": [{"id": "FR-1", "text": "post", "evidence_refs": ["CBPOST1M"]}]}]

    result = asyncio.run(generate_stories_for_epic(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        epic=epic, brd_sections_for_epic=sections,
        relevant_refs=["CBPOST1M", "CBPOST1M.2100-POST-TRAN"],
        known_requirement_ids=["FR-1"]))

    assert isinstance(result, EnrichmentResult)
    assert result.ok is True
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["schema"] is STORIES_SCHEMA
    assert call["system"] is STORIES_SYSTEM
    assert call["max_turns"] == 5
    # Scoped to THIS epic: its id/title/outcome appear; epic_id binding instruction present.
    assert "EPIC-1" in call["prompt"]
    assert "Posting" in call["prompt"]
    assert "epic_id" in call["prompt"]
    # AC-citation instructions present.
    assert "Given/When/Then" in call["prompt"]
    # The full per-epic relevant refs are inlined (no truncation).
    assert "CBPOST1M.2100-POST-TRAN" in call["prompt"]


def test_generate_stories_for_epic_prompt_excludes_other_epics():
    runner = FakeRunner({"stories": []})
    epic = {"id": "EPIC-2", "title": "Reporting", "outcome": "Emit statements"}
    sections = [{"requirements": [{"id": "FR-9", "evidence_refs": ["CBSTMT"]}]}]

    asyncio.run(generate_stories_for_epic(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        epic=epic, brd_sections_for_epic=sections,
        relevant_refs=["CBSTMT"], known_requirement_ids=["FR-9"]))

    prompt = runner.calls[0]["prompt"]
    # No other epic's identifiers / content leak into this per-epic prompt.
    assert "EPIC-1" not in prompt
    assert "Posting" not in prompt
    assert "EPIC-2" in prompt and "Reporting" in prompt


def test_generate_stories_for_epic_inlines_all_cited_refs_no_truncation():
    runner = FakeRunner({"stories": []})
    epic = {"id": "EPIC-1", "title": "Big", "outcome": "Everything"}
    cited = [f"PGM{i}" for i in range(300)]  # this epic legitimately cites 300 refs
    sections = [{"requirements": [{"id": "FR-1", "evidence_refs": cited}]}]

    asyncio.run(generate_stories_for_epic(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        epic=epic, brd_sections_for_epic=sections,
        relevant_refs=cited, known_requirement_ids=["FR-1"]))

    prompt = runner.calls[0]["prompt"]
    refs_block = prompt.split("Known graph evidence refs (cite only these)")[1]
    inlined = json.loads(refs_block.split("```json\n")[1].split("\n```")[0])
    assert len(inlined) == 300
    assert set(inlined) == set(cited)


def test_generate_stories_for_epic_passes_through_failure_cause():
    runner = FakeRunner({})
    result = asyncio.run(generate_stories_for_epic(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        epic={"id": "EPIC-1", "title": "T", "outcome": "O"},
        brd_sections_for_epic=[{"requirements": [{"id": "FR-1"}]}],
        relevant_refs=["CBPOST1M"], known_requirement_ids=["FR-1"]))
    assert result.ok is False
    assert result.payload == {}
    assert result.cause is not None


def test_split_schemas_produce_parse_backlog_compatible_objects():
    """A merged {epics, stories} built from the two split outputs must parse cleanly."""
    epics_out = {"epics": [{
        "id": "EPIC-1", "title": "Posting", "outcome": "Apply transactions",
        "brd_requirement_ids": ["FR-1"], "story_ids": ["US-1"],
        "evidence_refs": ["CBPOST1M"]}]}
    stories_out = {"stories": [{
        "id": "US-1", "epic_id": "EPIC-1", "title": "Post valid tx",
        "actor": "posting batch", "narrative": "As a batch I post.",
        "brd_requirement_ids": ["FR-1"],
        "acceptance_criteria": [{
            "id": "AC-1", "statement": "Valid amount updates balance.",
            "evidence_refs": ["CBPOST1M.2100-POST-TRAN"]}],
        "evidence_refs": ["CBPOST1M.2100-POST-TRAN"]}]}
    merged = {"epics": epics_out["epics"], "stories": stories_out["stories"]}

    backlog = parse_backlog_payload(
        merged, repo_slug="carddemo",
        known_refs={"CBPOST1M", "CBPOST1M.2100-POST-TRAN"},
        known_requirement_ids={"FR-1"})
    assert backlog.epics[0].id == "EPIC-1"
    assert backlog.stories[0].epic_id == "EPIC-1"
    assert backlog.stories[0].acceptance_criteria[0].id == "AC-1"
