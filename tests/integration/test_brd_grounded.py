import cobol_modernizer.agent.graph_ops as ops
from cobol_modernizer.agent.brd_judge import ajudge
from cobol_modernizer.brd.renderer import render_html
from cobol_modernizer.brd.schema import BRD, Strategy, Rating

class FakeRunner:
    async def run_structured(self, **kw):
        return {"items": [
            {"dimension": d, "score": 4, "rationale": "ok"} for d in
            ("completeness", "accuracy", "clarity", "consistency", "actionability")],
            "feedback": []}

async def test_grounded_brd_renders_with_judge_score(monkeypatch):
    monkeypatch.setattr(ops, "known_refs", lambda deps: {"PROG-A", "COPY-B"})
    brd = BRD(sections=[], evidence_map={"FR-1": ["PROG-A"], "FR-2": ["COPY-B"]},
              repo_id="sample", model="claude-sonnet-4-6", strategy=Strategy.map_reduce)
    report = await ajudge(brd, deps=object(), runner=FakeRunner(), model="m")
    assert report.weighted_score > 0
    assert report.rating in (Rating.high, Rating.medium, Rating.low)
    assert report.groundedness_failures == []     # fully grounded
    html = render_html(brd)
    assert isinstance(html, str) and "<html" in html.lower()
