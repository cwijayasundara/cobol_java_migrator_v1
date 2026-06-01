from cobol_modernizer.enrichment.seams import enrich_seams

_CANDS = [
    {"program": "CBACT01M", "seam_type": "db_reader",
     "signals": {"risk": 0.2}, "score": {"weighted": 0.9},
     "evidence_map": {"reads": ["CBACT01M"]}},
    {"program": "CBPOST1M", "seam_type": "db_writer",
     "signals": {"risk": 0.8}, "score": {"weighted": 0.4},
     "evidence_map": {"writes": ["CBPOST1M"]}},
]


class _Runner:
    """Returns a batched result; one good ref, one hallucinated ref."""
    async def run_structured(self, **kw):
        return {"items": [
            {"program": "CBACT01M", "rationale": "reader, low risk",
             "cited_refs": ["CBACT01M"]},
            {"program": "CBPOST1M", "rationale": "writer, identity drift",
             "cited_refs": ["GHOST"]},
            {"program": "NOT_A_SEAM", "rationale": "noise", "cited_refs": []},
            "garbage-not-a-dict",
        ]}


async def test_enrich_seams_grounds_and_skips_garbage():
    out = await enrich_seams(_CANDS, {"CBACT01M", "CBPOST1M"},
                             runner=_Runner(), model="m", timeout_s=5)
    assert set(out) == {"CBACT01M", "CBPOST1M"}
    assert out["CBACT01M"]["grounded"] is True
    assert out["CBACT01M"]["cited_refs"] == ["CBACT01M"]
    assert out["CBPOST1M"]["grounded"] is False
    assert out["CBPOST1M"]["cited_refs"] == []


class _EmptyRunner:
    async def run_structured(self, **kw):
        return {}


async def test_enrich_seams_empty_on_no_llm_output():
    out = await enrich_seams(_CANDS, {"CBACT01M"}, runner=_EmptyRunner(),
                             model="m", timeout_s=5)
    assert out == {}
