from __future__ import annotations

from typing import Any, Protocol

from cobol_modernizer.seam.schema import SeamSignals


class GraphClient(Protocol):
    def run(self, query: str, **params: Any) -> list[dict[str, Any]]: ...


_FAN_IN = """
// fan_in
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})
WHERE p.qualified_name = $program OR p.simple_name = $program
OPTIONAL MATCH (caller:CodeEntity {repo: $repo})-[c:CALLS]->(p)
WHERE coalesce(c.type, 'call') = 'call'
WITH p, count(DISTINCT caller) AS fan_in,
     exists((p)<-[:CALLS*0..]-(:CodeEntity {repo: $repo, is_external: true})) AS is_entry
RETURN fan_in, is_entry
"""

_MAX_FAN_IN = """
// max_fan_in
MATCH (:CodeEntity {repo: $repo})-[c:CALLS]->(p:CodeEntity {repo: $repo, kind: 'Program'})
WHERE coalesce(c.type,'call') = 'call'
WITH p, count(*) AS fi RETURN coalesce(max(fi), 1) AS max_fan_in
"""

_TOUCHED_RESOURCES = """
// touched_resources
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
WHERE p.qualified_name = $program OR p.simple_name = $program
WITH res, collect(DISTINCT CASE type(r) WHEN 'WRITES' THEN 'write'
                  WHEN 'READS' THEN 'read' ELSE coalesce(r.intent,'read') END) AS intents
OPTIONAL MATCH (other:CodeEntity {repo: $repo, kind: 'Program'})-[:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
WHERE NOT (other.qualified_name = $program OR other.simple_name = $program)
WITH res, intents, count(DISTINCT other) AS others
RETURN res.simple_name AS resource,
       CASE WHEN 'write' IN intents THEN 'write' ELSE 'read' END AS intent,
       others > 0 AS shared, others = 0 AS exclusive
"""

_GOTO_COUNT = """
// goto_count
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[:CONTAINS*1..2]->(para:CodeEntity)
WHERE p.qualified_name = $program OR p.simple_name = $program
OPTIONAL MATCH (para)-[g:GO_TO]->(:CodeEntity)
RETURN count(g) AS goto_count
"""

_BILLING_AUDIT = """
// billing_audit
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
WHERE (p.qualified_name = $program OR p.simple_name = $program)
  AND any(m IN ['BILL','AUDIT','TRAN','LEDGER','BAL','POST'] WHERE toUpper(res.simple_name) CONTAINS m)
RETURN count(res) AS hits
"""

_CHURN = """
// churn
MATCH (p:CodeEntity {repo: $repo, kind: 'Program'})
WHERE p.qualified_name = $program OR p.simple_name = $program
OPTIONAL MATCH (p)-[cc:CO_CHANGED_WITH]-(:CodeEntity)
WITH coalesce(sum(cc.times), 0) AS churn
MATCH (q:CodeEntity {repo: $repo, kind: 'Program'})
OPTIONAL MATCH (q)-[cc2:CO_CHANGED_WITH]-(:CodeEntity)
WITH churn, q, coalesce(sum(cc2.times),0) AS c2
RETURN churn, coalesce(max(c2), 1) AS max_churn
"""


def _one(rows: list[dict], key: str, default: Any = 0) -> Any:
    return rows[0].get(key, default) if rows else default


def raw_signals_for_program(client: GraphClient, *, repo: str, program: str) -> SeamSignals:
    fi_rows = client.run(_FAN_IN, repo=repo, program=program)
    fan_in = float(_one(fi_rows, "fan_in", 0))
    is_entry = bool(_one(fi_rows, "is_entry", False))
    max_fan_in = float(_one(client.run(_MAX_FAN_IN, repo=repo), "max_fan_in", 1)) or 1.0

    touched = client.run(_TOUCHED_RESOURCES, repo=repo, program=program)
    n_touched = len(touched) or 1
    n_shared = sum(1 for t in touched if t.get("shared"))
    n_exclusive = sum(1 for t in touched if t.get("exclusive"))
    is_writer = any(t.get("intent") == "write" for t in touched)
    reader_only = (not is_writer) and len(touched) > 0

    goto = float(_one(client.run(_GOTO_COUNT, repo=repo, program=program), "goto_count", 0))
    billing = float(_one(client.run(_BILLING_AUDIT, repo=repo, program=program), "hits", 0))
    churn_rows = client.run(_CHURN, repo=repo, program=program)
    churn = float(_one(churn_rows, "churn", 0))
    max_churn = float(_one(churn_rows, "max_churn", 1)) or 1.0

    # normalized fan-in (0..1) + a 0.25 entry-point bonus, capped at 1.0.
    business = min(min(fan_in / max_fan_in, 1.0) + (0.25 if is_entry else 0.0), 1.0)
    isolation = 1.0 - (n_shared / n_touched) if touched else 1.0
    testability = (1.0 if reader_only else 0.4) - min(goto / 10.0, 0.4)
    data_ownership = n_exclusive / n_touched if touched else 0.0
    risk = (0.5 if is_writer else 0.0) + (0.3 if billing > 0 else 0.0) \
           + 0.2 * min(churn / max_churn, 1.0)

    return SeamSignals(business=round(business, 6), isolation=round(isolation, 6),
                       testability=round(testability, 6),
                       data_ownership=round(data_ownership, 6), risk=round(risk, 6))
