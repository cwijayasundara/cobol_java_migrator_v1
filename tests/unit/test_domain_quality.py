from cobol_modernizer.domain.deterministic import generate_deterministic_domain_design
from cobol_modernizer.domain.quality import assess_domain_quality


class _Client:
    def run(self, query, **params):
        if "WRITES]->(x:CodeEntity)" in query:
            return [{"program": "P1", "writes": ["ACCTFILE"]}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "P1"}, {"q": "ACCTFILE"}]
        return []


def test_deterministic_domain_design_is_macro_first_and_grounded():
    backlog = '{"epics":[{"id":"E1","title":"Transaction Posting"}],"stories":[{"id":"US-1","epic_id":"E1","title":"Post valid transaction","evidence_refs":["P1"]}]}'
    dd = generate_deterministic_domain_design(
        _Client(), "repo", brd_text="BRD", backlog_json=backlog)

    assert [c.name for c in dd.contexts] == ["TransactionPosting"]
    assert dd.contexts[0].topology.deployment == "microservice"
    assert dd.designs[0].aggregates[0].methods == ["postValidTransaction"]


def test_domain_quality_reports_blockers():
    dd = generate_deterministic_domain_design(
        _Client(), "repo", brd_text="BRD",
        backlog_json='{"stories":[{"id":"US-1","title":"Post","evidence_refs":["P1"]}]}')
    dd.designs[0].api_surface = ""
    dd.designs[0].aggregates[0].methods = []

    passed, result, threshold = assess_domain_quality(
        dd, known_refs={"P1", "ACCTFILE"}, backlog_json='{"stories":[{"id":"US-1"}]}')

    assert not passed
    assert result["designs_without_api"] == [dd.designs[0].context]
    assert result["anemic_aggregates"]
    assert threshold["require_non_anemic_aggregates"] is True
