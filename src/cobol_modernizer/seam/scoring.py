from __future__ import annotations

from cobol_modernizer.seam.schema import SeamScore, SeamSignals

# Master plan §3 Phase 4 formula. risk subtracts.
WEIGHTS: dict[str, float] = {
    "business": 0.25, "isolation": 0.20, "testability": 0.20,
    "data_ownership": 0.20, "risk": -0.15,
}


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def score_signals(s: SeamSignals) -> SeamScore:
    normalized = {
        "business": clamp01(s.business), "isolation": clamp01(s.isolation),
        "testability": clamp01(s.testability),
        "data_ownership": clamp01(s.data_ownership), "risk": clamp01(s.risk),
    }
    weighted = sum(WEIGHTS[k] * v for k, v in normalized.items())
    return SeamScore(weighted=round(weighted, 6), normalized=normalized)
