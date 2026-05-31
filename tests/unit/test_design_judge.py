from cobol_modernizer.design.schema import BoundedContext, ServiceDesign
from cobol_modernizer.design.judge import judge_design


def _design(owned, evidence):
    return ServiceDesign(
        slice_id="posting", deployment="modular_monolith",
        context=BoundedContext.transaction_processing,
        owned_resources=owned, transition_pattern="extract_product_lines+legacy_mimic",
        components=["PostingService"], evidence_map=evidence)


KNOWN = {"CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC", "TRANSACT", "ACCTDAT"}


def test_clean_design_passes_high():
    d = _design(["TRANSACT", "ACCTDAT"],
                {"DR-1": ["CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC"]})
    rep = judge_design(d, known_refs=KNOWN, external_writers={})
    assert rep.data_ownership_ok is True
    assert rep.groundedness_failures == []
    assert rep.rating == "high"


def test_ownership_leak_fails():
    # ACCTDAT is also written by another context's program -> shared-write leak
    d = _design(["TRANSACT", "ACCTDAT"], {"DR-1": ["CBTRN02C"]})
    rep = judge_design(d, known_refs=KNOWN,
                       external_writers={"ACCTDAT": ["COACTUPC"]})
    assert rep.data_ownership_ok is False
    assert rep.rating == "low"


def test_hallucinated_evidence_floors_rating():
    d = _design(["TRANSACT"], {"DR-1": ["NOSUCHPGM"]})
    rep = judge_design(d, known_refs=KNOWN, external_writers={})
    assert "NOSUCHPGM" in rep.groundedness_failures
    assert rep.rating == "low"
