from cobol_modernizer.slice.gates import story_behavior_gate


def test_story_behavior_gate_requires_acceptance_and_equivalence():
    result = story_behavior_gate(
        story_id="US-1",
        acceptance_criteria_ids=["AC-1"],
        generated_test_refs=["AC-1"],
        equivalence_verdict="passed",
    )

    assert result["passed"] is True


def test_story_behavior_gate_fails_without_equivalence():
    result = story_behavior_gate(
        story_id="US-1",
        acceptance_criteria_ids=["AC-1"],
        generated_test_refs=["AC-1"],
        equivalence_verdict="not_run",
    )

    assert result["passed"] is False
    assert "equivalence" in result["reason"]
