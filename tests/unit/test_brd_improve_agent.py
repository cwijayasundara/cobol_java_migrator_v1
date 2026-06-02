import pytest

from cobol_modernizer.agent.brd_improve import agenerate_brd_improvement
from cobol_modernizer.agent.brd_schema import BRDDraft
from cobol_modernizer.brd.schema import Strategy


class _Runner:
    def __init__(self):
        self.seen = {}

    async def run_structured(self, **kw):
        self.seen = kw
        return {"sections": [{"title": "Non-functional Requirements",
                              "body_markdown": "added detail", "requirements": []}],
                "evidence_map": {"NFR-1": ["CBACT01M"]}}


class _EmptyRunner:
    async def run_structured(self, **kw):
        return {}


def _deps():
    from cobol_modernizer.agent.deps import GraphDeps
    from pathlib import Path

    class _C:
        def run(self, *a, **k):
            return []
    return GraphDeps(client=_C(), repo_id="demo", repo_path=Path("/tmp"))


async def test_improve_passes_current_brd_and_instruction_and_returns_draft():
    r = _Runner()
    draft, strategy = await agenerate_brd_improvement(
        _deps(), current_brd="## Current BRD\n(old content)",
        instruction="expand the non-functional requirements",
        runner=r, model="m", max_turns=20, timeout_s=10)
    assert isinstance(draft, BRDDraft)
    assert strategy == Strategy.single_shot
    assert draft.sections[0].title == "Non-functional Requirements"
    assert "(old content)" in r.seen["prompt"]
    assert "expand the non-functional requirements" in r.seen["prompt"]
    assert r.seen["label"] == "brd-improve"


async def test_improve_raises_on_empty_output():
    with pytest.raises(ValueError):
        await agenerate_brd_improvement(
            _deps(), current_brd="x", instruction="y",
            runner=_EmptyRunner(), model="m", max_turns=20, timeout_s=10)
