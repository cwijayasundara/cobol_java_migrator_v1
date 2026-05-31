import json
from pathlib import Path

from cobol_modernizer.slice.selection import pick_slice, SliceChoice

FIX = Path(__file__).parents[1] / "fixtures" / "seam_candidates_sample.json"


def test_picks_reader_only_top_ranked():
    candidates = json.loads(FIX.read_text())
    choice = pick_slice(candidates)
    assert isinstance(choice, SliceChoice)
    assert choice.program == "COACTVWC"
    assert choice.reader_only is True
    assert choice.score == 0.91
    # evidence carries the deterministic signals — NO LLM re-scoring
    assert choice.evidence["writes"] == 0
    assert choice.evidence["reads"] == 3


def test_rejects_when_no_reader_only_candidate():
    writers_only = [{"program": "X", "fan_in": 1, "fan_out": 1,
                     "reader_only": False, "writes": 1, "reads": 0, "score": 0.5}]
    import pytest
    with pytest.raises(ValueError, match="no reader-only seam"):
        pick_slice(writers_only)


def test_ties_break_by_lower_fan_out_then_name():
    cands = [
        {"program": "BBB", "fan_in": 1, "fan_out": 2, "reader_only": True,
         "writes": 0, "reads": 1, "score": 0.5},
        {"program": "AAA", "fan_in": 1, "fan_out": 1, "reader_only": True,
         "writes": 0, "reads": 1, "score": 0.5},
    ]
    assert pick_slice(cands).program == "AAA"  # lower fan_out wins the tie
