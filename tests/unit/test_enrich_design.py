from cobol_modernizer.enrichment.design import enrich_design

_DESIGNS = [
    {"slice_id": "P1-slice", "context": "account_management",
     "owned_resources": ["ACCT-MASTER"], "components": ["P1Service", "P1Repository"],
     "evidence_map": {"DR-1": ["P1"]}},
]


class _Runner:
    async def run_structured(self, **kw):
        return {"items": [{
            "slice_id": "P1-slice",
            "adrs": [{"number": 1, "title": "Single writer", "context": "c",
                      "decision": "d", "consequences": "q", "alternatives": "a"}],
            "component_descriptions": ["P1Service handles posting"],
            "api_surface": "POST /accounts", "data_model_notes": "ACCT-MASTER -> Account",
            "cited_refs": ["P1", "GHOST"]}]}


async def test_enrich_design_grounds_and_maps_by_slice():
    out = await enrich_design(_DESIGNS, {"P1"}, runner=_Runner(),
                              model="m", timeout_s=5)
    d = out["P1-slice"]
    assert d["adrs"][0]["alternatives"] == "a"
    assert d["api_surface"] == "POST /accounts"
    assert d["cited_refs"] == ["P1"]            # GHOST dropped (not in graph)
