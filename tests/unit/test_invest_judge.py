import pytest
from cobol_modernizer.planner.invest import judge_story, INVEST_SCHEMA
from cobol_modernizer.planner.schema import Story


class FakeRunner:
    def __init__(self, payload): self.payload = payload
    async def run_structured(self, **kw):
        self.kw = kw
        return self.payload


@pytest.mark.asyncio
async def test_invest_pass():
    runner = FakeRunner({"independent":4,"negotiable":4,"valuable":5,
                         "estimable":4,"small":4,"testable":5})
    story = Story(id="S1", title="Account view", seam="COACTVWC",
                  evidence_map={"seam": ["COACTVWC"]})
    report = await judge_story(story, known_refs={"COACTVWC"}, runner=runner,
                               model="claude-sonnet-4-6")
    assert report["passed"] is True
    assert runner.kw["schema"] is INVEST_SCHEMA and runner.kw["server"] is None


@pytest.mark.asyncio
async def test_hallucinated_seam_floors_score_and_fails():
    runner = FakeRunner({"independent":5,"negotiable":5,"valuable":5,
                         "estimable":5,"small":5,"testable":5})
    story = Story(id="S9", title="ghost", seam="GHOSTPGM",
                  evidence_map={"seam": ["GHOSTPGM"]})
    report = await judge_story(story, known_refs={"COACTVWC"}, runner=runner,
                               model="claude-sonnet-4-6")
    assert report["groundedness_failures"] == ["GHOSTPGM"]
    assert report["invest"]["valuable"] == 2      # floored
    assert report["passed"] is False
