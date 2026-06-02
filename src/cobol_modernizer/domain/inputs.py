"""Assemble a COMPACT, bounded graph-coupling summary for the Phase-1 decomposition
prompt. Bounded on purpose (top-N writers, cross-reads of owned resources, co-change
above a confidence floor) so the prompt stays well under the context window."""
from __future__ import annotations

from typing import Any

_WRITERS = """
// writers
MATCH (p:CodeEntity {repo:$repo}) WHERE p.kind = 'Program'
OPTIONAL MATCH (p)-[w:WRITES]->(x:CodeEntity)
WITH p, collect(DISTINCT coalesce(w.resource, x.simple_name, x.qualified_name)) AS writes
WHERE size([z IN writes WHERE z IS NOT NULL]) > 0
RETURN p.qualified_name AS program, [z IN writes WHERE z IS NOT NULL] AS writes
ORDER BY program LIMIT $top_n
"""

_CROSS_READS = """
// cross_reads
MATCH (w:CodeEntity {repo:$repo, kind:'Program'})-[wr:WRITES]->(res)
MATCH (r:CodeEntity {repo:$repo, kind:'Program'})-[:READS]->(res)
WHERE r.qualified_name <> w.qualified_name
RETURN DISTINCT r.qualified_name AS reader,
       coalesce(wr.resource, res.simple_name) AS resource,
       w.qualified_name AS writer
ORDER BY reader, resource LIMIT $top_n
"""

_CALLS = """
// calls
MATCH (a:CodeEntity {repo:$repo, kind:'Program'})-[c:CALLS]->(b:CodeEntity {repo:$repo, kind:'Program'})
WHERE coalesce(c.type,'call') = 'call'
RETURN DISTINCT a.qualified_name AS caller, b.qualified_name AS callee
ORDER BY caller, callee LIMIT $top_n
"""

_CO_CHANGE = """
// co_change
MATCH (a:CodeEntity {repo:$repo, kind:'Program'})-[cc:CO_CHANGED_WITH]->(b:CodeEntity {repo:$repo, kind:'Program'})
WHERE cc.times >= $floor
RETURN a.qualified_name AS a, b.qualified_name AS b, cc.times AS times
ORDER BY times DESC LIMIT $top_n
"""


def graph_coupling_summary(client: Any, repo: str, *, top_n: int = 60,
                           cochange_floor: int = 2) -> dict[str, Any]:
    return {
        "writers": client.run(_WRITERS, repo=repo, top_n=top_n),
        "cross_reads": client.run(_CROSS_READS, repo=repo, top_n=top_n * 4),
        "calls": client.run(_CALLS, repo=repo, top_n=top_n * 4),
        "co_change": client.run(_CO_CHANGE, repo=repo, floor=cochange_floor, top_n=top_n * 2),
    }
