from cobol_modernizer.domain.schema import BoundedContextDecl
from cobol_modernizer.domain.topology import (
    extract_score, deployment_for, assign_extraction_ranks, EXTRACT_THRESHOLD,
)


def test_extract_score_high_isolation_high_ownership_extracts():
    score = extract_score(isolation_mean=0.9, data_ownership_mean=0.9,
                          business_mean=0.8, risk_mean=0.1, inbound_norm=0.0)
    assert score > EXTRACT_THRESHOLD
    assert deployment_for(score) == "microservice"


def test_extract_score_low_isolation_stays_module():
    score = extract_score(isolation_mean=0.1, data_ownership_mean=0.1,
                          business_mean=0.2, risk_mean=0.8, inbound_norm=1.0)
    assert deployment_for(score) == "module"


def test_extraction_ranks_leaf_first_then_value():
    a = BoundedContextDecl(name="A", business_capability="", member_programs=["p"])
    b = BoundedContextDecl(name="B", business_capability="", member_programs=["q"])
    a.identity_drift = True
    a.topology = None
    b.topology = None
    ranked = assign_extraction_ranks([a, b], inbound={"A": 1, "B": 0},
                                     business={"A": 0.9, "B": 0.5})
    by_name = {c.name: c.extraction_rank for c in ranked}
    assert by_name["B"] < by_name["A"]
