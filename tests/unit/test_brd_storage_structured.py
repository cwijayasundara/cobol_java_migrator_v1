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


def test_save_passes_sections_to_client(monkeypatch):
    captured = {}

    class _FakeClient:
        def run(self, query, **params):
            captured.update(params)
            return [{"version": 2}]

    from cobol_modernizer.brd.schema import (
        BRD, Strategy, JudgeReport, Rating, Dimension, DimensionScore,
    )
    from cobol_modernizer.brd.schema import BRDSection  # noqa: F401
    st = BRDStorage(_FakeClient())
    report = JudgeReport(
        dimensions={d: DimensionScore(score=4, rationale="") for d in Dimension},
        weighted_score=4.0, rating=Rating.high, feedback=[], groundedness_failures=[])
    monkeypatch.setattr(BRDStorage, "_write_html",
                        lambda self, r, v, h: __import__("pathlib").Path("/tmp/x.html"))
    st.save(repo_id="demo", html="<html/>", judge_report=report, attempt_history=[],
            model="m", strategy=Strategy.single_shot, token_usage={},
            sections=[{"title": "Scope", "body_markdown": "s", "requirements": []}],
            evidence_map={"FR-1": ["P1"]})
    import json as _json
    assert _json.loads(captured["sections"])[0]["title"] == "Scope"
    assert _json.loads(captured["evidence_map"]) == {"FR-1": ["P1"]}
