import json

import pytest

from cobol_modernizer.backlog.generator import build_backlog_prompt, parse_backlog_payload
from cobol_modernizer.enrichment.refs import relevant_refs


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
