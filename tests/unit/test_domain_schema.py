from cobol_modernizer.domain.schema import (
    DecompositionMap, BoundedContextDecl, TopologyDecision, ContextDependency,
    ContextDesign, Aggregate, CobolMapping, DomainDesign,
)


def test_bounded_context_round_trips():
    ctx = BoundedContextDecl(
        name="Posting", business_capability="Post financial transactions",
        member_programs=["CBTRN02C"], owned_resources=["TRANSACT"],
        depends_on=[ContextDependency(target="Account", style="sync",
                                      reason="reads balance", cited_refs=["CBTRN02C"])],
        topology=TopologyDecision(deployment="microservice", score=0.71,
                                  inputs={"isolation_mean": 0.8}, rationale="high isolation"),
        extraction_rank=1, identity_drift=False, cited_refs=["FR-1", "CBTRN02C"])
    dumped = ctx.model_dump(mode="json")
    assert DecompositionMap(repo_slug="r", contexts=[ctx], unassigned_programs=[],
                            cited_refs=[]).contexts[0].topology.deployment == "microservice"
    assert dumped["depends_on"][0]["style"] == "sync"


def test_context_design_and_domain_design():
    cd = ContextDesign(
        context="Posting",
        aggregates=[Aggregate(name="Transaction", root_entity="Transaction",
                              invariants=["amount != 0"], entities=["Transaction"],
                              value_objects=["Money"], methods=["post"])],
        value_objects=["Money"], domain_services=["PostingService"],
        repositories=["TransactionRepository"], domain_events=["TransactionPosted"],
        api_surface="POST /transactions",
        cobol_mapping=[CobolMapping(cobol_ref="CBTRN02C.2800-UPDATE", maps_to="Transaction.post",
                                    note="paragraph folds into method")],
        cited_refs=["CBTRN02C"])
    dd = DomainDesign(repo_slug="r", version=1, rating="high", weighted_score=0.8,
                      contexts=[], designs=[cd], cited_refs=[])
    assert dd.designs[0].aggregates[0].methods == ["post"]
    assert dd.model_dump(mode="json")["designs"][0]["context"] == "Posting"
