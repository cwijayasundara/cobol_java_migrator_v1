from cobol_modernizer.backlog.dependency import derive_story_dependencies
from cobol_modernizer.backlog.schema import AcceptanceCriterion, UserStory


def _story(story_id, refs):
    return UserStory(
        id=story_id,
        epic_id="EPIC-1",
        title=story_id,
        actor="operator",
        narrative=f"As an operator I need {story_id}.",
        brd_requirement_ids=["FR-1"],
        acceptance_criteria=[AcceptanceCriterion(id=f"AC-{story_id}", statement="works")],
        evidence_refs=refs,
    )


def test_writer_story_depends_on_reader_story_for_same_resource():
    stories = [_story("US-READ", ["CBACT01M"]), _story("US-WRITE", ["CBPOST1M"])]
    seam_candidates = [
        {"program": "CBACT01M", "reads": ["ACCTFILE"], "writes": [], "score": {"weighted": 0.9}},
        {"program": "CBPOST1M", "reads": ["ACCTFILE"], "writes": ["ACCTFILE"], "score": {"weighted": 0.4}},
    ]

    dag = derive_story_dependencies(stories, seam_candidates, repo_slug="carddemo-mini")

    by_id = {s.id: s for s in dag.stories}
    assert by_id["US-WRITE"].depends_on == ["US-READ"]
    assert dag.repo_slug == "carddemo-mini"
