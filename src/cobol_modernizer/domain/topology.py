"""Deterministic topology recommendation + strangler-fig extraction order.

The LLM proposes context MEMBERSHIP; these pure functions decide module-vs-service
from the SAME seam signals the seam engine already computes (consistency with the
Phase-4 weighted formula is deliberate)."""
from __future__ import annotations

from cobol_modernizer.domain.schema import BoundedContextDecl

EXTRACT_THRESHOLD = 0.55


def extract_score(*, isolation_mean: float, data_ownership_mean: float,
                  business_mean: float, risk_mean: float, inbound_norm: float) -> float:
    """Higher = more justified to extract as a standalone microservice."""
    return (0.30 * isolation_mean + 0.25 * data_ownership_mean
            + 0.20 * business_mean - 0.15 * risk_mean - 0.10 * inbound_norm)


def deployment_for(score: float) -> str:
    return "microservice" if score >= EXTRACT_THRESHOLD else "module"


def assign_extraction_ranks(contexts: list[BoundedContextDecl], *,
                            inbound: dict[str, int],
                            business: dict[str, float]) -> list[BoundedContextDecl]:
    """Strangler-fig order: leaf contexts (fewest inbound data deps) first, tie-broken
    by business value desc. Identity-drift contexts (others read their data) sink to
    the end ('keep shared / extract last'). Mutates + returns the list."""
    def key(c: BoundedContextDecl) -> tuple:
        return (1 if c.identity_drift else 0,
                inbound.get(c.name, 0),
                -business.get(c.name, 0.0),
                c.name)
    for rank, c in enumerate(sorted(contexts, key=key), start=1):
        c.extraction_rank = rank
    return contexts
