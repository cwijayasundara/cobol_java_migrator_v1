from cobol_modernizer.domain.schema import (
    DecompositionMap, BoundedContextDecl, ContextDesign, Aggregate, TopologyDecision,
)
from cobol_modernizer.domain.assemble import assemble


def _decl(name, owned):
    return BoundedContextDecl(name=name, business_capability="c", member_programs=["P"],
                              owned_resources=owned,
                              topology=TopologyDecision(deployment="module", score=0.1),
                              cited_refs=["P"])


def test_assemble_rates_and_collects_warnings():
    dm = DecompositionMap(repo_slug="r", contexts=[_decl("A", ["ACCT"])])
    designs = [ContextDesign(context="A", aggregates=[
        Aggregate(name="Account", root_entity="Account", invariants=["x"], methods=["m"])],
        repositories=["AccountRepository"], cited_refs=["P"])]
    dd = assemble("r", dm, designs, version=3)
    assert dd.version == 3
    assert dd.rating in {"high", "medium", "low"}
    assert dd.contexts[0].name == "A"
    assert dd.designs[0].context == "A"


def test_assemble_low_rating_when_anemic():
    dm = DecompositionMap(repo_slug="r", contexts=[_decl("A", ["ACCT"])])
    designs = [ContextDesign(context="A", aggregates=[
        Aggregate(name="Account", root_entity="Account")], cited_refs=["P"])]
    dd = assemble("r", dm, designs, version=1)
    assert dd.rating == "low"   # anemic + uncovered resource


def test_assemble_warns_on_async_dep_without_producer_event():
    from cobol_modernizer.domain.schema import ContextDependency
    a = _decl("A", [])
    a.depends_on = [ContextDependency(target="B", style="async", reason="needs B events")]
    b = _decl("B", [])
    dm = DecompositionMap(repo_slug="r", contexts=[a, b])
    designs = [
        ContextDesign(context="A", aggregates=[Aggregate(name="AA", root_entity="AA",
                      invariants=["i"], methods=["m"])], repositories=["AA"], cited_refs=["P"]),
        ContextDesign(context="B", aggregates=[Aggregate(name="BB", root_entity="BB",
                      invariants=["i"], methods=["m"])], repositories=["BB"],
                      domain_events=[], cited_refs=["P"]),  # no events -> warning
    ]
    dd = assemble("r", dm, designs, version=1)
    assert any("async dependency A->B" in w for w in __import__("cobol_modernizer.domain.assemble",
               fromlist=["cross_context_integration_warnings"]).cross_context_integration_warnings(dm, designs))
    assert dd.rating in {"medium", "low"}   # the async-without-event warning lowers it
