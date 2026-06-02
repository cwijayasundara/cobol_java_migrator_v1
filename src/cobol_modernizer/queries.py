"""Repo-scoped Cypher query helpers over a Neo4j client.

CodeGraphQueries centralizes the read-side query helpers so callers (graph_ops,
the seam scorer, MCP tools) share one repo-scoping + name-match convention. The
v2 seam-discovery methods (reader/writer classification, data accesses, seam
candidates) are added on top — pure Cypher, ZERO LLM in the scoring path.
"""
from __future__ import annotations


class CodeGraphQueries:
    def __init__(self, client) -> None:
        self.client = client

    # ---- shared query-building helpers ----

    @staticmethod
    def _name_match(alias: str) -> str:
        """A WHERE fragment matching `$name` against an entity's qualified or simple name."""
        return f"({alias}.qualified_name = $name OR {alias}.simple_name = $name)"

    @staticmethod
    def _repo_filter(alias: str, repo: str | None) -> str:
        """An `AND <alias>.repo = $repo` clause when repo-scoped, else empty.
        Always used after an existing WHERE so the AND is well-formed."""
        return f"AND {alias}.repo = $repo" if repo else ""

    @staticmethod
    def _params(repo: str | None, **kwargs) -> dict:
        """Query params; includes `repo` only when set (so `$repo` is referenced
        only by queries that actually scope on it)."""
        params = dict(kwargs)
        if repo is not None:
            params["repo"] = repo
        return params

    # ---- v2 seam-discovery queries (Cypher only; ZERO LLM) ----

    # Resource names that imply a financial side-effect (billing/audit/ledger).
    SIDE_EFFECT_MARKERS = ["TRANSACT", "TRANSACTION", "BILL", "PAYMENT",
                           "LEDGER", "AUDIT", "POSTING", "BALANCE"]

    def data_accesses(self, program: str, *, intent: str | None = None,
                      repo: str | None = None) -> list[dict]:
        """All file/VSAM/CICS/SQL accesses by a program, normalized to
        {resource, kind, intent, mode}. intent is derived: READS / CICS read /
        SQL read -> 'read'; WRITES / CICS write / SQL write -> 'write'."""
        return self.client.run(
            f"""
            // accesses_for_program
            MATCH (p:CodeEntity)-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
            WHERE {self._name_match("p")}
            {self._repo_filter("p", repo)}
            WITH res, r, type(r) AS rk,
                 CASE
                   WHEN type(r) = 'READS' THEN 'read'
                   WHEN type(r) = 'WRITES' THEN 'write'
                   ELSE coalesce(r.intent, 'read')
                 END AS derived_intent
            WHERE $intent IS NULL OR derived_intent = $intent
            RETURN res.qualified_name AS resource, rk AS kind,
                   derived_intent AS intent, r.mode AS mode
            ORDER BY resource, kind
            """,
            **self._params(repo, name=program, intent=intent),
        )

    def reader_writer_classification(self, resource: str,
                                     repo: str | None = None) -> dict:
        """The pivotal Fowler reader-vs-writer split for one resource, in-DB.
        A program is a WRITER if it has any write-intent edge to the resource;
        otherwise (read-only access) it is a READER."""
        rows = self.client.run(
            f"""
            MATCH (p:CodeEntity)-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
            WHERE (toLower(res.simple_name) = toLower($resource)
                   OR toLower(res.qualified_name) = toLower($resource))
            {self._repo_filter("p", repo)}
            WITH p,
                 CASE
                   WHEN type(r) = 'WRITES' THEN 'write'
                   WHEN type(r) = 'READS' THEN 'read'
                   ELSE coalesce(r.intent, 'read')
                 END AS intent
            WITH p.qualified_name AS program,
                 collect(DISTINCT intent) AS intents
            RETURN program, ('write' IN intents) AS is_writer
            ORDER BY program
            """,
            **self._params(repo, resource=resource),
        )
        readers = [{"program": r["program"]} for r in rows if not r["is_writer"]]
        writers = [{"program": r["program"]} for r in rows if r["is_writer"]]
        return {"resource": resource, "readers": readers, "writers": writers}

    def seam_candidates(self, repo: str | None = None, limit: int = 20) -> list[dict]:
        """Rank programs as strangler-fig seam candidates. Reader-only programs
        score highest; writers and side-effecting (billing/audit) programs lower.
        Fan-in = distinct CALLS callers; fan-out = distinct resources touched.
        ALL signals computed in Cypher — no LLM in this path."""
        return self.client.run(
            f"""
            MATCH (p:CodeEntity {{kind: 'Program'}})
            WHERE true {self._repo_filter("p", repo)}
            OPTIONAL MATCH (p)-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
            WITH p, res, r,
                 CASE WHEN type(r) = 'WRITES' THEN true
                      WHEN type(r) IN ['EXECUTES_CICS','EXECUTES_SQL']
                           AND coalesce(r.intent,'read') = 'write' THEN true
                      ELSE false END AS is_write
            WITH p,
                 count(DISTINCT res) AS fan_out,
                 sum(CASE WHEN is_write THEN 1 ELSE 0 END) AS write_count,
                 sum(CASE WHEN is_write AND any(m IN $markers
                      WHERE res.simple_name CONTAINS m
                            OR res.qualified_name CONTAINS m) THEN 1 ELSE 0 END) AS side_effects
            OPTIONAL MATCH (caller:CodeEntity)-[:CALLS]->(p)
            WITH p, fan_out, write_count, side_effects,
                 count(DISTINCT caller) AS fan_in
            WITH p, fan_out, fan_in, write_count, side_effects,
                 (write_count = 0) AS reader_only
            WITH p, fan_out, fan_in, write_count, side_effects, reader_only,
                 ( (CASE WHEN reader_only THEN 0.5 ELSE 0.0 END)
                 + (CASE WHEN fan_out > 0 THEN 0.2 ELSE 0.0 END)
                 + (1.0 / (1.0 + fan_in)) * 0.2
                 - (CASE WHEN side_effects > 0 THEN 0.3 ELSE 0.0 END)
                 ) AS score
            RETURN p.qualified_name AS program, fan_in, fan_out,
                   write_count, side_effects, reader_only, score
            ORDER BY score DESC, fan_in ASC, program
            LIMIT $limit
            """,
            **self._params(repo, markers=self.SIDE_EFFECT_MARKERS, limit=limit),
        )

    # ---- cockpit graph reads (read-only; shaped for the UI GraphView/EntityDrawer) ----

    def graph_overview(self, repo: str | None = None, limit: int = 300) -> dict:
        """Read-only: nodes (capped at limit) + the relationships among them, shaped
        for the cockpit GraphView (nodes:{id,name,kind,file,summary}, links:{source,target,type})."""
        node_rows = self.client.run(
            """
            MATCH (n:CodeEntity)
            WHERE $repo IS NULL OR n.repo = $repo
            RETURN n.qualified_name AS id, n.simple_name AS name, n.kind AS kind,
                   n.file_path AS file, n.semantic_summary AS summary
            LIMIT $limit
            """,
            repo=repo, limit=limit,
        )
        ids = [r["id"] for r in node_rows]
        link_rows = self.client.run(
            """
            MATCH (a:CodeEntity)-[r]->(b:CodeEntity)
            WHERE a.qualified_name IN $ids AND b.qualified_name IN $ids
            RETURN a.qualified_name AS source, b.qualified_name AS target, type(r) AS type
            """,
            ids=ids,
        )
        return {"nodes": node_rows, "links": link_rows}

    def neighbors_of(self, qualified_name: str, *, repo: str | None = None,
                     limit: int = 50) -> dict:
        """Read-only: the entities one hop from `qualified_name` (either direction)
        plus the relationships connecting them to it — same {nodes, links} shape as
        graph_overview. Powers the cockpit's double-click-to-expand: pulls in
        neighbors that the capped initial overview may have left out."""
        rows = self.client.run(
            """
            MATCH (n:CodeEntity {qualified_name: $q})-[r]-(m:CodeEntity)
            WHERE $repo IS NULL OR m.repo = $repo
            RETURN m.qualified_name AS id, m.simple_name AS name, m.kind AS kind,
                   m.file_path AS file, m.semantic_summary AS summary,
                   startNode(r).qualified_name AS source,
                   endNode(r).qualified_name AS target, type(r) AS type
            LIMIT $limit
            """,
            q=qualified_name, repo=repo, limit=limit,
        )
        nodes: dict[str, dict] = {}
        links: dict[tuple[str, str, str], dict] = {}
        for r in rows:
            nodes.setdefault(r["id"], {"id": r["id"], "name": r["name"],
                                      "kind": r["kind"], "file": r["file"],
                                      "summary": r["summary"]})
            key = (r["source"], r["target"], r["type"])
            links.setdefault(key, {"source": r["source"], "target": r["target"],
                                   "type": r["type"]})
        return {"nodes": list(nodes.values()), "links": list(links.values())}

    def entity_detail(self, qualified_name: str) -> dict | None:
        """Read-only: an entity's props + incoming/outgoing relationships, shaped for
        the cockpit EntityDetail. Returns None if the entity is unknown."""
        ent = self.client.run(
            "MATCH (n:CodeEntity {qualified_name: $q}) RETURN properties(n) AS props",
            q=qualified_name,
        )
        if not ent:
            return None
        incoming = self.client.run(
            """
            MATCH (s:CodeEntity)-[r]->(n:CodeEntity {qualified_name: $q})
            RETURN s.qualified_name AS source, s.kind AS source_kind, type(r) AS relationship
            """, q=qualified_name,
        )
        outgoing = self.client.run(
            """
            MATCH (n:CodeEntity {qualified_name: $q})-[r]->(t:CodeEntity)
            RETURN t.qualified_name AS target, t.kind AS target_kind, type(r) AS relationship
            """, q=qualified_name,
        )
        return {"entity": ent[0]["props"], "incoming": incoming, "outgoing": outgoing}
