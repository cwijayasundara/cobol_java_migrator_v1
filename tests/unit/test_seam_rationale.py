import pytest
from cobol_modernizer.seam.rationale import awrite_rationale, RATIONALE_SCHEMA


class FakeRunner:
    def __init__(self, payload): self.payload = payload
    async def run_structured(self, **kw):
        self.kw = kw
        return self.payload


@pytest.mark.asyncio
async def test_rationale_drops_hallucinated_refs():
    runner = FakeRunner({"rationale": "Reader-only, low blast radius.",
                         "cited_refs": ["COACTVWC", "GHOSTPGM"]})
    out = await awrite_rationale(
        program="COACTVWC",
        evidence={"isolation": ["COACTVWC"], "risk": ["COACTVWC"]},
        known_refs={"COACTVWC"}, runner=runner, model="claude-sonnet-4-6")
    assert out["grounded"] is False                      # GHOSTPGM not known
    assert out["cited_refs"] == ["COACTVWC"]             # hallucinated ref dropped
    assert "blast radius" in out["rationale"]
    # invariants: single turn, no server, json_schema schema passed through
    assert runner.kw["max_turns"] == 1 and runner.kw["server"] is None
    assert runner.kw["schema"] is RATIONALE_SCHEMA


@pytest.mark.asyncio
async def test_grounded_rationale_when_all_refs_known():
    runner = FakeRunner({"rationale": "ok", "cited_refs": ["COACTVWC"]})
    out = await awrite_rationale(program="COACTVWC", evidence={"isolation": ["COACTVWC"]},
                                 known_refs={"COACTVWC"}, runner=runner,
                                 model="claude-sonnet-4-6")
    assert out["grounded"] is True
