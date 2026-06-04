import pytest
from cobol_modernizer.domain.schema import BoundedContextDecl
from cobol_modernizer.domain.tactical import (
    design_all_contexts,
    design_context,
    design_context_decomposed,
)


class _Runner:
    def __init__(self):
        self.labels = []

    async def run_structured(self, **kw):
        self.labels.append(kw.get("label", ""))
        if "domain-contract" in kw.get("label", ""):
            return {"repositories": ["AccountRepository"], "domain_events": ["Posted"],
                    "api_surface": "POST /accounts", "cited_refs": ["P1"]}
        if "domain-mapping" in kw.get("label", ""):
            return {"cobol_mapping": [{"cobol_ref": "P1", "maps_to": "Account.post",
                                       "note": "folds in"}],
                    "cited_refs": ["P1", "GHOST"]}
        return {"aggregates": [{"name": "Account", "root_entity": "Account",
                                "invariants": ["balance >= 0"], "methods": ["post"]}],
                "value_objects": ["Money"], "domain_services": ["PostingService"],
                "repositories": ["AccountRepository"], "domain_events": ["Posted"],
                "api_surface": "POST /accounts",
                "cobol_mapping": [{"cobol_ref": "P1.2800", "maps_to": "Account.post",
                                   "note": "folds in"}],
                "cited_refs": ["P1", "GHOST"]}


def _ctx(name="Acct"):
    return BoundedContextDecl(name=name, business_capability="accounts",
                              member_programs=["P1"], owned_resources=["ACCT"],
                              cited_refs=["P1"])


@pytest.mark.asyncio
async def test_design_context_grounds_refs():
    cd = await design_context(_ctx(), known_refs={"P1"}, runner=_Runner(),
                              model="m", timeout_s=5)
    assert cd.context == "Acct"
    assert cd.aggregates[0].methods == ["post"]
    assert cd.cited_refs == ["P1"]   # GHOST dropped


@pytest.mark.asyncio
async def test_design_all_contexts_parallel():
    ctxs = [_ctx("A"), _ctx("B")]
    out = await design_all_contexts(ctxs, known_refs={"P1"}, runner=_Runner(),
                                    model="m", timeout_s=5)
    assert {c.context for c in out} == {"A", "B"}


@pytest.mark.asyncio
async def test_design_context_decomposed_splits_tactical_units():
    runner = _Runner()
    cd = await design_context_decomposed(_ctx(), known_refs={"P1"}, runner=runner,
                                         model="m", timeout_s=5)
    assert cd.context == "Acct"
    assert cd.aggregates[0].name == "Account"
    assert cd.repositories == ["AccountRepository"]
    assert cd.cobol_mapping[0].maps_to == "Account.post"
    assert cd.cited_refs == ["P1"]
    assert runner.labels == [
        "domain-aggregate:Acct",
        "domain-contract:Acct",
        "domain-mapping:Acct",
    ]
