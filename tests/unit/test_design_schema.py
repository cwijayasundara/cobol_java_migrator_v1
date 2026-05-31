from cobol_modernizer.design.schema import (
    BoundedContext, ServiceDesign, ADR, DesignResult,
)


def test_bounded_context_enum_has_four_carddemo_contexts():
    values = {c.value for c in BoundedContext}
    assert values == {
        "account_management", "card_management",
        "transaction_processing", "bill_pay_reporting",
    }


def test_service_design_carries_evidence_map_and_data_ownership():
    d = ServiceDesign(
        slice_id="posting-cbtrn02c",
        deployment="modular_monolith",
        context=BoundedContext.transaction_processing,
        owned_resources=["TRANSACT", "ACCTDAT", "TCATBAL"],
        transition_pattern="extract_product_lines+legacy_mimic",
        components=["PostingService", "AccountBalanceRepository"],
        evidence_map={"DR-1": ["CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC"]},
    )
    assert d.context is BoundedContext.transaction_processing
    assert "ACCTDAT" in d.owned_resources
    assert d.evidence_map["DR-1"] == ["CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC"]


def test_adr_is_numbered_and_has_decision_and_consequences():
    adr = ADR(number=1, title="Modular monolith for posting slice",
              status="accepted", context="Writer slice, identity-drift risk",
              decision="Extract Product Lines + Legacy Mimic write-back",
              consequences="COBOL estate keeps running via ACL",
              evidence_refs=["CBTRN02C"])
    assert adr.number == 1 and adr.status == "accepted"


def test_design_result_aggregates_design_and_adrs():
    d = ServiceDesign(slice_id="s", deployment="modular_monolith",
                      context=BoundedContext.transaction_processing,
                      owned_resources=["ACCTDAT"],
                      transition_pattern="extract_product_lines+legacy_mimic",
                      components=["PostingService"], evidence_map={"DR-1": ["CBTRN02C"]})
    res = DesignResult(design=d, adrs=[], rating="high", weighted_score=4.4)
    assert res.rating == "high"
