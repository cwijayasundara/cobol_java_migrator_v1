"""Deterministic gates for the Domain Design stage. Each returns a list of human-readable
violation strings (empty = pass). They never raise; the orchestrator decides repair-vs-fail."""
from __future__ import annotations

from cobol_modernizer.domain.schema import BoundedContextDecl, ContextDesign
from cobol_modernizer.enrichment.base import ground_refs


def check_coverage(contexts: list[BoundedContextDecl], writers: set[str]) -> list[str]:
    assigned: dict[str, int] = {}
    for c in contexts:
        for p in c.member_programs:
            assigned[p] = assigned.get(p, 0) + 1
    out = [f"{p} not assigned to any context" for p in sorted(writers) if p not in assigned]
    out += [f"{p} assigned to multiple contexts"
            for p, n in sorted(assigned.items()) if n > 1 and p in writers]
    return out


def check_data_ownership(contexts: list[BoundedContextDecl]) -> list[str]:
    owners: dict[str, list[str]] = {}
    for c in contexts:
        for r in c.owned_resources:
            owners.setdefault(r, []).append(c.name)
    return [f"resource {r} owned by multiple contexts: {', '.join(sorted(names))}"
            for r, names in sorted(owners.items()) if len(set(names)) > 1]


def check_acyclic(contexts: list[BoundedContextDecl]) -> list[str]:
    names = {c.name for c in contexts}
    graph: dict[str, list[str]] = {c.name: [] for c in contexts}
    for c in contexts:
        for dep in c.depends_on:
            if dep.target not in names:
                return [f"dependency target {dep.target} is not a known context"]
            graph[c.name].append(dep.target)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in names}

    def visit(n: str) -> bool:
        color[n] = GRAY
        for m in graph[n]:
            if color[m] == GRAY or (color[m] == WHITE and visit(m)):
                return True
        color[n] = BLACK
        return False

    for n in names:
        if color[n] == WHITE and visit(n):
            return [f"dependency cycle detected involving {n}"]
    return []


def check_grounded(contexts: list[BoundedContextDecl], known_refs: set[str]) -> list[str]:
    out: list[str] = []
    for c in contexts:
        refs = list(c.cited_refs) + list(c.member_programs)
        _grounded, ok = ground_refs(refs, known_refs)
        if not ok:
            bad = sorted(set(refs) - set(_grounded))
            out.append(f"context {c.name} cites ungrounded refs: {', '.join(bad)}")
    return out


def check_data_coverage(decl: BoundedContextDecl, design: ContextDesign) -> list[str]:
    covered = {agg.name for agg in design.aggregates} | set(design.repositories)
    covered |= {e for agg in design.aggregates for e in agg.entities}
    out = []
    blob = " ".join(covered).upper()
    for r in decl.owned_resources:
        token = r.replace("-", "").replace("_", "").upper()
        if token and token not in blob.replace("-", "").replace("_", ""):
            out.append(f"context {decl.name}: owned resource {r} not in any aggregate/repository")
    return out


def anemic_warnings(design: ContextDesign) -> list[str]:
    return [f"aggregate {a.name} has no invariants or methods (anemic)"
            for a in design.aggregates if not a.invariants and not a.methods]


def run_phase1_gates(contexts: list[BoundedContextDecl], writers: set[str],
                     known_refs: set[str]) -> list[str]:
    return (check_coverage(contexts, writers) + check_data_ownership(contexts)
            + check_acyclic(contexts) + check_grounded(contexts, known_refs))
