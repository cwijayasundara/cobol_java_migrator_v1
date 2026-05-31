from cobol_modernizer.seams.scoring import SeamScorer


class _FakeQueries:
    """Stand-in for CodeGraphQueries returning canned Cypher rows."""
    def seam_candidates(self, repo=None, limit=20):
        return [
            {"program": "CBACT01C", "fan_in": 0, "fan_out": 1, "write_count": 0,
             "side_effects": 0, "reader_only": True, "score": 0.9},
            {"program": "COBIL00C", "fan_in": 2, "fan_out": 1, "write_count": 1,
             "side_effects": 1, "reader_only": False, "score": -0.13},
        ]


def test_ranks_reader_only_first_and_builds_evidence_map():
    scorer = SeamScorer(_FakeQueries(), repo="carddemo")
    out = scorer.rank(limit=10)
    assert [c.program for c in out] == ["CBACT01C", "COBIL00C"]
    top = out[0]
    assert top.reader_only is True
    # lineage: every candidate carries an evidence_map referencing its program id
    assert "CBACT01C" in top.evidence_map["seam:CBACT01C"]
    assert out[1].reader_only is False and out[1].side_effects == 1
