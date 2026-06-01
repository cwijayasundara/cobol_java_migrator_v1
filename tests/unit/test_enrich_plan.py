from cobol_modernizer.enrichment.plan import enrich_plan

_STORIES = [
    {"id": "S1", "title": "Migrate P1", "seam": "P1", "depends_on": [],
     "evidence_map": {"seam": ["P1"]}},
    {"id": "S2", "title": "Migrate P2", "seam": "P2", "depends_on": ["S1"],
     "evidence_map": {"seam": ["GHOST"]}},
]
_WAVES = [["S1"], ["S2"]]


class _Runner:
    async def run_structured(self, **kw):
        return {
            "stories": [
                {"story_id": "S1", "invest": {"independent": 5, "negotiable": 4,
                  "valuable": 5, "estimable": 4, "small": 4, "testable": 5},
                 "description": "Extract P1 reader", "acceptance_criteria": ["AC1"]},
                {"story_id": "S2", "invest": {"independent": 3, "negotiable": 3,
                  "valuable": 5, "estimable": 5, "small": 3, "testable": 3},
                 "description": "Extract P2 writer", "acceptance_criteria": ["AC2"]},
            ],
            "edge_rationale": {"S2->S1": "P2 writes what P1 reads"},
            "wave_narrative": [{"wave": 0, "narrative": "ship readers first"},
                               {"wave": 1, "narrative": "then writers"}],
        }


async def test_enrich_plan_per_story_and_delivery():
    out = await enrich_plan(_STORIES, _WAVES, {"P1"}, runner=_Runner(),
                            model="m", timeout_s=5)
    assert out["stories"]["S1"]["description"] == "Extract P1 reader"
    assert out["stories"]["S1"]["invest"]["valuable"] == 5
    # groundedness floor: S2 cites GHOST (not in {"P1"}) -> valuable/estimable capped at 2
    assert out["stories"]["S2"]["invest"]["valuable"] == 2
    assert out["stories"]["S2"]["invest"]["estimable"] == 2
    assert out["stories"]["S2"]["groundedness_failures"] == ["GHOST"]
    assert out["delivery"]["edge_rationale"]["S2->S1"] == "P2 writes what P1 reads"
    assert out["delivery"]["wave_narrative"][0]["narrative"] == "ship readers first"
