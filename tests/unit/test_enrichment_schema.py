from cobol_modernizer.enrichment.schema import (
    DesignNarrative, PlanDeliveryNarrative, SeamNarrative, StoryNarrative,
)


def test_defaults_are_safe_empty():
    assert SeamNarrative(program="P").grounded is False
    assert StoryNarrative(story_id="S1").acceptance_criteria == []
    assert PlanDeliveryNarrative().edge_rationale == {}
    assert DesignNarrative(slice_id="x").adrs == []


def test_round_trips_to_json():
    sn = SeamNarrative(program="P", rationale="r", cited_refs=["P"], grounded=True)
    assert sn.model_dump()["program"] == "P"
