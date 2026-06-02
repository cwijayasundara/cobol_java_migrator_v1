from cobol_modernizer.domain.schema import (
    DomainDesign, BoundedContextDecl, ContextDesign, Aggregate, TopologyDecision,
)
from cobol_modernizer.domain.render import render_html


def test_render_contains_context_and_topology():
    dd = DomainDesign(repo_slug="r", version=2, rating="high", weighted_score=1.0,
        contexts=[BoundedContextDecl(name="Posting", business_capability="post tx",
                  member_programs=["CBTRN02C"], owned_resources=["TRANSACT"],
                  topology=TopologyDecision(deployment="microservice", score=0.7),
                  extraction_rank=1, cited_refs=["CBTRN02C"])],
        designs=[ContextDesign(context="Posting", aggregates=[
            Aggregate(name="Transaction", root_entity="Transaction",
                      invariants=["amount != 0"], methods=["post"])],
            api_surface="POST /transactions", cited_refs=["CBTRN02C"])])
    html = render_html(dd)
    assert "<html" in html.lower()
    assert "Posting" in html and "microservice" in html
    assert "Transaction" in html and "POST /transactions" in html
