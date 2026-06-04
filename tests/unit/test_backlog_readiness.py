from cobol_modernizer.backlog.generator import generate_deterministic_backlog, parse_backlog_payload
from cobol_modernizer.backlog.readiness import assess_backlog_readiness


SECTIONS = [{
    "title": "Posting",
    "requirements": [
        {"id": "FR-1", "text": "post valid transaction"},
        {"id": "FR-2", "text": "reject invalid transaction"},
    ],
}]
KNOWN_REFS = {"CBPOST1M", "CBPOST1M.2100-POST"}


def _backlog(payload):
    return parse_backlog_payload(
        payload, repo_slug="carddemo-mini", known_refs=KNOWN_REFS,
        known_requirement_ids={"FR-1", "FR-2"})


def test_backlog_readiness_passes_grounded_requirement_complete_backlog():
    payload = generate_deterministic_backlog(
        brd_sections=SECTIONS,
        known_refs=sorted(KNOWN_REFS),
        known_requirement_ids=["FR-1", "FR-2"],
        brd_evidence_map={
            "FR-1": ["CBPOST1M"],
            "FR-2": ["CBPOST1M.2100-POST"],
        },
    )
    passed, result, threshold = assess_backlog_readiness(
        _backlog(payload), brd_sections=SECTIONS, known_refs=KNOWN_REFS,
        graph_coverage_ratio=1.0, min_graph_coverage=0.8)

    assert passed
    assert result["requirement_coverage_ratio"] == 1.0
    assert result["missing_requirement_ids"] == []
    assert threshold["min_requirement_coverage"] == 1.0


def test_backlog_readiness_reports_blueprint_blockers():
    payload = {
        "epics": [{"id": "EPIC-1", "title": "Posting", "outcome": "post",
                   "brd_requirement_ids": ["FR-1"], "story_ids": ["US-1"],
                   "evidence_refs": ["CBPOST1M"]}],
        "stories": [{"id": "US-1", "epic_id": "EPIC-1", "title": "Post",
                     "actor": "user", "narrative": "As a user I post.",
                     "brd_requirement_ids": ["FR-1"],
                     "acceptance_criteria": [{"id": "AC-1", "statement": "posts",
                                              "evidence_refs": []}],
                     "evidence_refs": ["CBPOST1M"]}],
    }
    passed, result, _ = assess_backlog_readiness(
        _backlog(payload), brd_sections=SECTIONS, known_refs=KNOWN_REFS,
        graph_coverage_ratio=0.5, min_graph_coverage=0.8)

    assert not passed
    assert result["missing_requirement_ids"] == ["FR-2"]
    assert result["acceptance_criteria_without_evidence"] == ["AC-1"]
    assert result["graph_coverage_ratio"] == 0.5
