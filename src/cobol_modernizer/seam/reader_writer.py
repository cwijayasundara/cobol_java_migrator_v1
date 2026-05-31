from __future__ import annotations

from typing import Any, Protocol


class GraphClient(Protocol):
    def run(self, query: str, **params: Any) -> list[dict[str, Any]]: ...


# Read-only. Normalizes READS/WRITES + CICS/SQL intent into (program, resource, intent).
_ACCESSES_FOR_PROGRAM = """
// accesses_for_program
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
WHERE p.qualified_name = $program OR p.simple_name = $program
WITH res.simple_name AS resource,
     CASE type(r)
          WHEN 'READS'  THEN 'read'
          WHEN 'WRITES' THEN 'write'
          ELSE coalesce(r.intent, 'read')
     END AS intent
RETURN DISTINCT $program AS program, resource, intent
"""

_READERS_OF_RESOURCE = """
// readers_of_resource
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS|EXECUTES_CICS|EXECUTES_SQL]->(res)
WHERE res.simple_name = $resource
  AND (type(r) = 'READS' OR coalesce(r.intent,'read') = 'read')
RETURN DISTINCT $resource AS resource, p.simple_name AS reader
"""


def classify_program(client: GraphClient, *, repo: str, program: str) -> dict[str, Any]:
    rows = client.run(_ACCESSES_FOR_PROGRAM, repo=repo, program=program)
    reads = sorted({r["resource"] for r in rows if r["intent"] == "read"})
    writes = sorted({r["resource"] for r in rows if r["intent"] == "write"})
    return {"program": program, "reads": reads, "writes": writes,
            "reader_only": len(writes) == 0 and len(reads) > 0}


def classify_resource(client: GraphClient, *, repo: str, resource: str) -> dict[str, Any]:
    readers = sorted({r["reader"] for r in
                      client.run(_READERS_OF_RESOURCE, repo=repo, resource=resource)})
    return {"resource": resource, "readers": readers}


def is_identity_drift_writer(client: GraphClient, *, repo: str, program: str) -> bool:
    """A writer is identity-drift-prone (must stay single-system) when it writes a
    resource that other programs also read: splitting it risks two systems disagreeing
    about the canonical value. Fowler: identity-drift writers stay single-system."""
    cls = classify_program(client, repo=repo, program=program)
    for resource in cls["writes"]:
        other_readers = [rd for rd in classify_resource(client, repo=repo,
                                                         resource=resource)["readers"]
                         if rd != program]
        if other_readers:
            return True
    return False
