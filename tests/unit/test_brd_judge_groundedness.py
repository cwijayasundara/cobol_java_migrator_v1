import cobol_modernizer.agent.graph_ops as ops
from cobol_modernizer.agent.brd_judge import ajudge
from cobol_modernizer.brd.schema import BRD, Strategy, Dimension, Rating


class FakeRunner:
    async def run_structured(self, **kw):
        return {"items": [
            {"dimension": "completeness", "score": 5, "rationale": ""},
            {"dimension": "accuracy", "score": 5, "rationale": ""},
            {"dimension": "clarity", "score": 5, "rationale": ""},
            {"dimension": "consistency", "score": 5, "rationale": ""},
            {"dimension": "actionability", "score": 5, "rationale": ""}],
            "feedback": []}


async def test_hallucinated_ref_forces_accuracy_to_2(monkeypatch):
    monkeypatch.setattr(ops, "known_refs", lambda deps: {"CBACT01C"})
    brd = BRD(sections=[], evidence_map={"FR-1": ["GHOST-PROGRAM"]},
              repo_id="cardemo", model="m", strategy=Strategy.map_reduce)
    report = await ajudge(brd, deps=object(), runner=FakeRunner(), model="m")
    assert report.dimensions[Dimension.accuracy].score == 2
    assert "GHOST-PROGRAM" in report.groundedness_failures
    assert report.rating != Rating.high   # floored accuracy blocks 'high'
