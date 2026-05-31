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
