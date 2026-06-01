"""The BRD judge must survive a weaker/cheaper model's format drift. A real Haiku
run returned a feedback item with dimension='Completeness' (capitalized) and the
old `FeedbackItem(**f)` construction raised a pydantic enum ValidationError that
crashed the whole BRD run. These tests pin the defensive parsing."""
from cobol_modernizer.agent.brd_judge import (
    _coerce_score, _norm_dimension, _parse_feedback, ajudge,
)
from cobol_modernizer.brd.schema import BRD, Dimension, Strategy


def test_norm_dimension_tolerates_case_and_whitespace():
    assert _norm_dimension("Completeness") == Dimension.completeness
    assert _norm_dimension("  ACCURACY ") == Dimension.accuracy
    assert _norm_dimension("nonsense") is None
    assert _norm_dimension(None) is None


def test_coerce_score_clamps_and_rejects():
    assert _coerce_score(3) == 3
    assert _coerce_score(9) == 5          # clamp high
    assert _coerce_score(0) == 1          # clamp low
    assert _coerce_score("not-a-number") is None
    assert _coerce_score(None) is None


def test_parse_feedback_skips_malformed_instead_of_crashing():
    items = _parse_feedback([
        {"dimension": "Completeness", "severity": "High",     # capitalized -> normalized
         "suggestion": "add scope", "target_section": "Scope"},
        {"dimension": "bogus", "severity": "low",             # bad dimension -> skipped
         "suggestion": "x", "target_section": "y"},
        {"dimension": "clarity", "severity": "urgent",        # bad severity -> skipped
         "suggestion": "x", "target_section": "y"},
        {"dimension": "accuracy", "severity": "low"},         # missing fields -> skipped
        "not even a dict",                                    # wrong type -> skipped
    ])
    assert len(items) == 1
    assert items[0].dimension == Dimension.completeness
    assert items[0].severity == "high"


class _DriftingRunner:
    """Mimics a weaker judge: capitalized dimension values everywhere."""
    async def run_structured(self, **kw):
        return {
            "items": [{"dimension": "Completeness", "score": 4, "rationale": "ok"}],
            "feedback": [{"dimension": "Completeness", "severity": "Medium",
                          "suggestion": "tighten scope", "target_section": "Scope"}],
        }


async def test_ajudge_does_not_crash_on_capitalized_enums(monkeypatch):
    import cobol_modernizer.agent.graph_ops as ops
    monkeypatch.setattr(ops, "known_refs", lambda deps: set())
    brd = BRD(sections=[], evidence_map={}, repo_id="r", model="m",
              strategy=Strategy.single_shot)
    report = await ajudge(brd, deps=object(), runner=_DriftingRunner(), model="m")
    # Capitalized 'Completeness' was normalized, not dropped, so it scored 4 (not the
    # default 3); the feedback item survived parsing.
    assert report.dimensions[Dimension.completeness].score == 4
    assert len(report.feedback) == 1
    assert report.feedback[0].dimension == Dimension.completeness
