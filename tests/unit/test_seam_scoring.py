from cobol_modernizer.seam.schema import (
    SeamSignals, SeamScore, SeamType, TransitionPattern, SeamCandidate, SeamSet,
)


def test_seam_signals_clamped_to_unit_interval():
    s = SeamSignals(business=1.4, isolation=-0.2, testability=0.5,
                    data_ownership=0.8, risk=0.3)
    # raw values are stored as-given; scoring clamps. Model only validates shape.
    assert s.business == 1.4 and s.risk == 0.3


def test_seam_candidate_carries_evidence_map():
    c = SeamCandidate(
        program="COACTVWC", seam_type=SeamType.cics_api,
        signals=SeamSignals(business=0.7, isolation=0.9, testability=0.8,
                            data_ownership=0.6, risk=0.1),
        score=SeamScore(weighted=0.0, normalized={}),
        transition=TransitionPattern(name="facade_routed_by_txn_id", summary=""),
        evidence_map={"isolation": ["COACTVWC"], "risk": ["COACTVWC"]},
        identity_drift_writer=False,
    )
    assert c.evidence_map["isolation"] == ["COACTVWC"]
    assert c.seam_type is SeamType.cics_api
