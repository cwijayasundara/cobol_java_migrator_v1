from cobol_modernizer.planner.schema import Story
from cobol_modernizer.planner.tagging import tag_stories_with_contexts


def test_story_has_optional_context_and_topology_defaulting_none():
    s = Story(id="S1", title="t", seam="P1")
    assert s.context is None and s.topology is None


def test_tag_stories_assigns_context_and_topology():
    stories = [Story(id="S1", title="t", seam="P1"), Story(id="S2", title="t", seam="P2")]
    contexts = [{"name": "Acct", "member_programs": ["P1"],
                 "topology": {"deployment": "microservice"}}]
    out = tag_stories_with_contexts(stories, contexts)
    assert out[0].context == "Acct" and out[0].topology == "microservice"
    assert out[1].context is None   # P2 not in any context
