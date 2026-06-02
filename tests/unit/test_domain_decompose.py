import pytest
from cobol_modernizer.domain.decompose import decompose


class _StubClient:
    """Minimal graph client: writers P1->R1, P2->R2; P2 reads R1 (P1 identity-drift)."""
    def run(self, query, **params):
        if "// writers" in query:
            return [{"program": "P1", "writes": ["R1"]}, {"program": "P2", "writes": ["R2"]}]
        if "// cross_reads" in query:
            return [{"reader": "P2", "resource": "R1", "writer": "P1"}]
        if "WRITES]->(x:CodeEntity)" in query:
            return [{"program": "P1", "writes": ["R1"]}, {"program": "P2", "writes": ["R2"]}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "P1"}, {"q": "P2"}]
        return []


def _signals(client, *, repo, program):
    from cobol_modernizer.seam.schema import SeamSignals
    table = {"P1": SeamSignals(business=0.5, isolation=0.2, testability=0.5,
                               data_ownership=0.3, risk=0.6),
             "P2": SeamSignals(business=0.9, isolation=0.9, testability=0.8,
                               data_ownership=0.9, risk=0.1)}
    return table[program]


class _Runner:
    async def run_structured(self, **kw):
        return {"contexts": [
            {"name": "Acct", "business_capability": "accounts", "member_programs": ["P1"],
             "owned_resources": ["R1"], "depends_on": [], "cited_refs": ["P1"]},
            {"name": "Tx", "business_capability": "transactions", "member_programs": ["P2"],
             "owned_resources": ["R2"],
             "depends_on": [{"target": "Acct", "style": "sync", "reason": "reads R1",
                             "cited_refs": ["P2"]}], "cited_refs": ["P2"]}],
            "unassigned_programs": [], "cited_refs": []}


@pytest.mark.asyncio
async def test_decompose_assigns_topology_ranks_and_passes_gates():
    dm = await decompose(_StubClient(), "repo", brd_text="BRD",
                         runner=_Runner(), model="m", timeout_s=5,
                         signals_fn=_signals)
    names = {c.name for c in dm.contexts}
    assert names == {"Acct", "Tx"}
    tx = next(c for c in dm.contexts if c.name == "Tx")
    acct = next(c for c in dm.contexts if c.name == "Acct")
    assert tx.topology.deployment == "microservice"
    assert acct.topology.deployment == "module"
    assert acct.identity_drift is True
    assert tx.extraction_rank < acct.extraction_rank


@pytest.mark.asyncio
async def test_decompose_raises_on_unrepairable_gate_violation():
    class _BadRunner:
        async def run_structured(self, **kw):
            return {"contexts": [{"name": "X", "business_capability": "c",
                                  "member_programs": ["P1"], "owned_resources": ["R1"],
                                  "depends_on": [], "cited_refs": ["P1"]}],
                    "unassigned_programs": [], "cited_refs": []}
    with pytest.raises(ValueError, match="domain decomposition failed gates"):
        await decompose(_StubClient(), "repo", brd_text="BRD", runner=_BadRunner(),
                        model="m", timeout_s=5, signals_fn=_signals, max_repairs=1)
