import json

from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.agent.brd_schema import BRDDraft


def test_reconstruct_draft_from_structured_node():
    node = {
        "sections": json.dumps([{"title": "Executive Summary",
                                 "body_markdown": "hello", "requirements": []}]),
        "evidence_map": json.dumps({"FR-1": ["CBACT01M"]}),
        "html": "<html>ignored</html>",
    }
    draft = BRDStorage.reconstruct_draft(node)
    assert isinstance(draft, BRDDraft)
    assert draft.sections[0].title == "Executive Summary"
    assert draft.evidence_map == {"FR-1": ["CBACT01M"]}


def test_reconstruct_draft_returns_none_for_legacy_html_only_node():
    assert BRDStorage.reconstruct_draft({"html": "<html>old</html>"}) is None
    assert BRDStorage.reconstruct_draft({"sections": None, "evidence_map": None}) is None
