"""Task 14: prove the seam signal/ranking Cypher runs against a real Neo4j 5.x with a
seeded v2 CardDemo subgraph (not a FakeClient). Reuses the shared `neo4j_graph`
fixture (conftest), which skips cleanly when Docker/testcontainers are unavailable."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

FIX = Path(__file__).parents[1] / "fixtures" / "carddemo_v2_subgraph.cypher"


@pytest.fixture
def seeded_client(neo4j_graph):
    for stmt in FIX.read_text().split(";"):
        if stmt.strip():
            neo4j_graph.run(stmt)
    return neo4j_graph


def test_coactvwc_signals_reader_only(seeded_client):
    from cobol_modernizer.seam.signals import raw_signals_for_program
    sig = raw_signals_for_program(seeded_client, repo="cardemo", program="COACTVWC")
    assert sig.risk == 0.0
    assert sig.testability == 1.0          # reader-only, no GO_TO


def test_cbtrn02c_is_writer_with_risk(seeded_client):
    from cobol_modernizer.seam.reader_writer import is_identity_drift_writer
    assert is_identity_drift_writer(seeded_client, repo="cardemo",
                                    program="CBTRN02C") is True


def test_ranking_puts_reader_first(seeded_client):
    from cobol_modernizer.seam.service import rank_candidates
    ranked = rank_candidates(seeded_client, repo="cardemo", limit=10)
    assert ranked[0]["program"] in ("COACTVWC", "CBACT01C")
    writer = next(c for c in ranked if c["program"] == "CBTRN02C")
    assert writer["identity_drift_writer"] is True
