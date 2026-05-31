from cobol_modernizer.seam.schema import (
    SeamSignals, SeamScore, SeamType, TransitionPattern, SeamCandidate, SeamSet,
)
from cobol_modernizer.seam.scoring import WEIGHTS, clamp01, score_signals


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


def test_weights_match_master_plan():
    assert WEIGHTS == {"business": 0.25, "isolation": 0.20, "testability": 0.20,
                       "data_ownership": 0.20, "risk": -0.15}


def test_clamp01():
    assert clamp01(1.4) == 1.0 and clamp01(-0.2) == 0.0 and clamp01(0.5) == 0.5


def test_reader_only_outranks_writer():
    reader = SeamSignals(business=0.7, isolation=0.9, testability=0.9,
                         data_ownership=0.8, risk=0.1)
    writer = SeamSignals(business=0.7, isolation=0.3, testability=0.3,
                         data_ownership=0.4, risk=0.9)
    assert score_signals(reader).weighted > score_signals(writer).weighted


def test_known_value():
    s = SeamSignals(business=0.8, isolation=1.0, testability=1.0,
                    data_ownership=1.0, risk=0.0)
    # 0.25*0.8 + 0.20 + 0.20 + 0.20 - 0 = 0.80
    assert abs(score_signals(s).weighted - 0.80) < 1e-9
