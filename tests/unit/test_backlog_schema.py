from cobol_modernizer.backlog.schema import AcceptanceCriterion, Epic, UserStory


def test_user_story_carries_brd_and_graph_lineage():
    story = UserStory(
        id="US-1",
        epic_id="EPIC-1",
        title="Post approved transaction",
        actor="batch posting operator",
        narrative="As a posting process I want approved transactions applied to accounts.",
        brd_requirement_ids=["FR-1"],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="AC-1",
                statement="Given a valid transaction, the account balance is updated.",
                evidence_refs=["CBPOST1M.2100-POST-TRAN"],
            )
        ],
        evidence_refs=["CBPOST1M", "CBPOST1M.2100-POST-TRAN"],
    )

    assert story.brd_requirement_ids == ["FR-1"]
    assert story.acceptance_criteria[0].evidence_refs == ["CBPOST1M.2100-POST-TRAN"]


def test_epic_groups_business_stories():
    epic = Epic(
        id="EPIC-1",
        title="Transaction Posting",
        outcome="Accurately apply daily transactions to account records.",
        brd_requirement_ids=["FR-1", "FR-2"],
        story_ids=["US-1", "US-2"],
        evidence_refs=["CBPOST1M"],
    )

    assert epic.story_ids == ["US-1", "US-2"]
