import pytest

from cobol_modernizer.backlog.generator import parse_backlog_payload


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
