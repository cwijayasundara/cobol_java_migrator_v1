"""Resolve a failing equivalence field back to the COBOL source seam that
produced it, via read-only graph traversal. Lineage is never invented: if the
graph has no writer/mover for the field, we fall back to the program node and
flag the link unresolved (so the defect ticket is honest about provenance)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SeamRef:
    entity_qname: str       # graph entity id (the source seam)
    edge_kind: str = ""     # WRITES | MOVES_TO | EXECUTES_CICS | ...
    file_path: str = ""
    line: int | None = None
    unresolved: bool = False


def resolve_source_seam(graph_ops, *, program: str, field: str) -> SeamRef:
    """Find the paragraph/program that writes or moves into `field`.
    `graph_ops` is the read-only Cypher facade (agent.graph_ops)."""
    qname = f"{program}.{field}"
    writers = graph_ops.writers_of_data_item(qname)
    if writers:
        w = writers[0]   # nearest writer; full list available in evidence
        return SeamRef(
            entity_qname=w["qualified_name"],
            edge_kind=w.get("edge", ""),
            file_path=w.get("file_path", ""),
            line=w.get("line"),
        )
    return SeamRef(entity_qname=program, unresolved=True)
