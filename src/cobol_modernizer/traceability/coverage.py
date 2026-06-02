from __future__ import annotations

from collections.abc import Mapping, Sequence

from cobol_modernizer.traceability.schema import LogicCoverageReport


_GRAPH_REFS_Q = """
MATCH (n:CodeEntity {repo:$repo})
WHERE n.kind IN ['Program', 'Paragraph', 'DataItem', 'Copybook', 'External']
RETURN n.qualified_name AS ref, n.kind AS kind
ORDER BY n.qualified_name
"""


def _all_graph_refs(neo4j, repo_slug: str) -> list[str]:
    rows = neo4j.run(_GRAPH_REFS_Q, repo=repo_slug)
    return [r["ref"] for r in rows if r.get("ref")]


def _covered_refs(evidence_map: Mapping[str, Sequence[str]]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for values in evidence_map.values():
        for ref in values:
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def brd_logic_coverage(
    neo4j,
    repo_slug: str,
    brd_sections: list[dict],
    evidence_map: Mapping[str, Sequence[str]],
    exclusions: Mapping[str, str] | None = None,
) -> LogicCoverageReport:
    _ = brd_sections  # Reserved for future requirement-aware filtering.
    all_refs = _all_graph_refs(neo4j, repo_slug)
    excluded = dict(exclusions or {})
    eligible_refs = [r for r in all_refs if r not in excluded]
    eligible_set = set(eligible_refs)
    covered = [r for r in _covered_refs(evidence_map) if r in eligible_set]
    covered_set = set(covered)
    uncovered = [r for r in eligible_refs if r not in covered_set]
    effective_total = len(eligible_refs)
    ratio = (len(covered) / effective_total) if effective_total else 1.0
    return LogicCoverageReport(
        repo_slug=repo_slug,
        total_refs=effective_total,
        covered_refs=covered,
        uncovered_refs=uncovered,
        exclusions=excluded,
        coverage_ratio=ratio,
    )
