import json

import pytest

import cobol_modernizer.brd.pipeline as pipe
from cobol_modernizer.brd.schema import (
    BRDResult, Rating, Strategy, JudgeReport, Dimension, DimensionScore,
)


class _Storage:
    def __init__(self):
        self.saved = None

    def get_latest(self, repo_id):
        return {"sections": json.dumps([{"title": "Scope", "body_markdown": "old",
                                         "requirements": []}]),
                "evidence_map": json.dumps({"FR-1": ["CBACT01M"]}),
                "html": "<html>old</html>"}

    def save(self, **kw):
        self.saved = kw
        from datetime import datetime, timezone
        return BRDResult(brd_id="b2", repo_id=kw["repo_id"], version=2,
                         rating=kw["judge_report"].rating,
                         weighted_score=kw["judge_report"].weighted_score,
                         attempts=1, attempt_history=[], model=kw["model"],
                         strategy=kw["strategy"], html_path="/tmp/v2.html",
                         created_at=datetime.now(timezone.utc), token_usage={})


async def _fake_improve(deps, *, current_brd, instruction, runner, model, max_turns,
                        timeout_s, **kw):
    from cobol_modernizer.agent.brd_schema import BRDDraft
    assert "old" in current_brd and instruction == "expand NFRs"
    return BRDDraft.model_validate(
        {"sections": [{"title": "Non-functional Requirements",
                       "body_markdown": "more", "requirements": []}],
         "evidence_map": {"NFR-1": ["CBACT01M"]}}), Strategy.single_shot


async def _fake_judge(brd, deps, *, runner, model):
    return JudgeReport(
        dimensions={d: DimensionScore(score=4, rationale="") for d in Dimension},
        weighted_score=4.0, rating=Rating.high, feedback=[], groundedness_failures=[])


def test_improve_pipeline_loads_latest_runs_agent_saves_new_version(monkeypatch):
    storage = _Storage()
    monkeypatch.setattr(pipe, "render_html", lambda brd: "<html>new</html>")
    monkeypatch.setattr("cobol_modernizer.agent.brd_improve.agenerate_brd_improvement",
                        _fake_improve)
    monkeypatch.setattr("cobol_modernizer.agent.brd_judge.ajudge", _fake_judge)

    class _Client:
        def run(self, *a, **k):
            return []
    result = pipe.improve_brd_graph_sync(
        "demo", "expand NFRs", client=_Client(), repo_path="/tmp", storage=storage)
    assert result.version == 2
    assert storage.saved["sections"][0]["title"] == "Non-functional Requirements"


def test_improve_pipeline_raises_when_no_brd(monkeypatch):
    class _NoStorage:
        def get_latest(self, repo_id):
            return None

    class _Client:
        def run(self, *a, **k):
            return []
    with pytest.raises(ValueError):
        pipe.improve_brd_graph_sync("demo", "x", client=_Client(), repo_path="/tmp",
                                    storage=_NoStorage())


def test_improve_pipeline_does_not_save_when_agent_raises(monkeypatch):
    storage = _Storage()
    monkeypatch.setattr(pipe, "render_html", lambda brd: "<html>new</html>")

    async def _boom(deps, *, current_brd, instruction, runner, model, max_turns, timeout_s, **kw):
        raise ValueError("improve agent produced no usable BRD draft")
    monkeypatch.setattr("cobol_modernizer.agent.brd_improve.agenerate_brd_improvement", _boom)

    class _Client:
        def run(self, *a, **k):
            return []
    with pytest.raises(ValueError):
        pipe.improve_brd_graph_sync("demo", "x", client=_Client(), repo_path="/tmp", storage=storage)
    assert storage.saved is None    # never overwrote the prior version
