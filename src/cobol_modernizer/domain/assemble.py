"""Phase 3: combine the decomposition + per-context designs into a rated DomainDesign,
checking cross-context invariants and folding gate warnings into a rating."""
from __future__ import annotations

from cobol_modernizer.domain.gates import anemic_warnings, check_data_coverage
from cobol_modernizer.domain.schema import ContextDesign, DecompositionMap, DomainDesign


def cross_context_warnings(dm: DecompositionMap, designs: list[ContextDesign]) -> list[str]:
    seen: dict[str, str] = {}
    out: list[str] = []
    for d in designs:
        for agg in d.aggregates:
            if agg.name in seen and seen[agg.name] != d.context:
                out.append(f"aggregate {agg.name} spans contexts {seen[agg.name]} and {d.context}")
            seen[agg.name] = d.context
    return out


def _rate(n_warnings: int) -> tuple[str, float]:
    if n_warnings == 0:
        return "high", 1.0
    if n_warnings <= 1:
        return "medium", 0.6
    return "low", 0.3


def assemble(repo_slug: str, dm: DecompositionMap, designs: list[ContextDesign],
             *, version: int = 0) -> DomainDesign:
    decl_by_name = {c.name: c for c in dm.contexts}
    warnings: list[str] = cross_context_warnings(dm, designs)
    for d in designs:
        decl = decl_by_name.get(d.context)
        if decl:
            warnings += check_data_coverage(decl, d)
        warnings += anemic_warnings(d)
    rating, score = _rate(len(warnings))
    cited = sorted({r for c in dm.contexts for r in c.cited_refs}
                   | {r for d in designs for r in d.cited_refs})
    return DomainDesign(repo_slug=repo_slug, version=version, rating=rating,
                        weighted_score=score, contexts=dm.contexts, designs=designs,
                        cited_refs=cited)
