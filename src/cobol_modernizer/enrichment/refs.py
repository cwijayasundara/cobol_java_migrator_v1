"""Deterministic, LOSSLESS relevance-scoping for graph refs.

Heavy LLM generators (backlog, technical design) blow their prompt budget when
they inline the ENTIRE graph (every CodeEntity qualified_name). This helper
inlines only the graph refs that a given in-scope slice of BRD content actually
cites: it walks the scope and keeps every string leaf that is a known ref.

HARD CONSTRAINT: this NEVER caps or truncates. There is no cap/limit/max
parameter and no ``[:N]`` slice. It returns ALL relevant refs. Call-size
bounding is achieved by DECOMPOSITION upstream (scoping the walk to a single
epic / requirement subset before calling), NOT by shortening the result here.

PURE: no I/O, no LLM, no Neo4j. Deterministic — same inputs yield the same
ordered output (first-seen during a depth-first walk, deduped)."""
from __future__ import annotations

from typing import Any


def relevant_refs(scope: Any, known_refs: list[str]) -> list[str]:
    """Collect every known ref cited anywhere in ``scope``, LOSSLESS.

    Walks ``scope`` (arbitrarily nested dicts/lists/tuples) depth-first and keeps
    each string leaf that is a member of ``set(known_refs)``. Order is first-seen
    during the walk; duplicates are collapsed. Refs not in ``known_refs`` are
    excluded (never invented). Returns the FULL ordered list — no cap, no padding.
    """
    known = set(known_refs)
    ordered: list[str] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            if node in known and node not in seen:
                seen.add(node)
                ordered.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
        # other leaf types (int/float/bool/None/...) are ignored

    walk(scope)
    return ordered
