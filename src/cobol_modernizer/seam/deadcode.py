from __future__ import annotations

from typing import Any, Protocol


class GraphClient(Protocol):
    def run(self, query: str, **params: Any) -> list[dict[str, Any]]: ...


# A paragraph is dead if (a) it belongs to the program, (b) it is NOT the entry
# paragraph, and (c) it is unreachable from the entry via PERFORM(CALLS type=perform)
# or GO_TO edges. Read-only.
#
# APOC-free: entry = paragraph with min start_line via an ordered subquery.
_DEAD_PARAGRAPHS_NO_APOC = """
MATCH (prog:CodeEntity {repo: $repo, kind: 'Program'})
WHERE prog.qualified_name = $program OR prog.simple_name = $program
MATCH (prog)-[:CONTAINS*1..2]->(entry:CodeEntity {repo: $repo, kind: 'Paragraph'})
WITH prog, entry ORDER BY entry.start_line LIMIT 1
MATCH (prog)-[:CONTAINS*1..2]->(para:CodeEntity {repo: $repo, kind: 'Paragraph'})
WHERE para <> entry
  AND NOT exists((entry)-[:CALLS|GO_TO*1..50]->(para))
RETURN DISTINCT para.qualified_name AS paragraph
ORDER BY paragraph
"""


def dead_paragraphs(client: GraphClient, *, repo: str, program: str) -> list[str]:
    rows = client.run(_DEAD_PARAGRAPHS_NO_APOC, repo=repo, program=program)
    return [r["paragraph"] for r in rows if r.get("paragraph")]
