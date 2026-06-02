from cobol_modernizer.controlplane.domain import run_domain_design


class _StubClient:
    def run(self, query, **params):
        if "// writers" in query or "WRITES]->(x:CodeEntity)" in query:
            return [{"program": "P1", "writes": ["R1"]}, {"program": "P2", "writes": ["R2"]}]
        if "// cross_reads" in query:
            return [{"reader": "P2", "resource": "R1", "writer": "P1"}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "P1"}, {"q": "P2"}]
        return []


def _signals(client, *, repo, program):
    from cobol_modernizer.seam.schema import SeamSignals
    return SeamSignals(business=0.8, isolation=0.8, testability=0.8,
                       data_ownership=0.8, risk=0.1)


class _Runner:
    async def run_structured(self, **kw):
        if "domain-decompose" in kw.get("label", ""):
            return {"contexts": [
                {"name": "Acct", "business_capability": "a", "member_programs": ["P1"],
                 "owned_resources": ["R1"], "depends_on": [], "cited_refs": ["P1"]},
                {"name": "Tx", "business_capability": "t", "member_programs": ["P2"],
                 "owned_resources": ["R2"], "depends_on": [], "cited_refs": ["P2"]}],
                "unassigned_programs": [], "cited_refs": []}
        return {"aggregates": [{"name": "Agg", "root_entity": "E", "invariants": ["i"],
                                "methods": ["m"]}], "repositories": ["R1Repository"],
                "api_surface": "GET /x", "cited_refs": ["P1"]}


def test_run_domain_design_end_to_end():
    dd = run_domain_design(_StubClient(), "repo", brd_text="BRD", runner=_Runner(),
                           model="m", timeout_s=5, signals_fn=_signals)
    assert {c.name for c in dd.contexts} == {"Acct", "Tx"}
    assert len(dd.designs) == 2
    assert dd.rating in {"high", "medium", "low"}
