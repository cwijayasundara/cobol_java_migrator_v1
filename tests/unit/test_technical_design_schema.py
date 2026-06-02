from cobol_modernizer.technical_design.schema import (
    ApiContract,
    PersistenceDesign,
    TechnicalDesign,
    TechnicalService,
)


def test_technical_design_links_service_to_context_and_stories():
    design = TechnicalDesign(
        repo_slug="carddemo-mini",
        services=[
            TechnicalService(
                name="posting-service",
                bounded_context="Posting",
                deployment="module",
                story_ids=["US-1"],
                api_contracts=[ApiContract(name="postTransaction", method="POST", path="/accounts/{id}/transactions")],
                persistence=[PersistenceDesign(resource="ACCTFILE", access_pattern="legacy-mimic")],
                evidence_refs=["CBPOST1M"],
            )
        ],
    )

    assert design.services[0].story_ids == ["US-1"]
    assert design.services[0].persistence[0].resource == "ACCTFILE"
