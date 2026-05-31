from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase

from cobol_modernizer import schema


class Neo4jClient:
    """Thin wrapper around the Neo4j Python driver for code graph operations."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        load_dotenv()
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "")
        # Suppress UNRECOGNIZED notifications: Neo4j warns whenever a query
        # references a label/relationship/property the DB has not yet seen
        # (e.g. HAS_BRD before the first BRD is written). They are cosmetic
        # and spam the log on every poll until the first write happens.
        self.driver = GraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            notifications_disabled_classifications=["UNRECOGNIZED"],
        )

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> Neo4jClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def apply_schema(self) -> None:
        with self.driver.session() as session:
            for stmt in schema.CONSTRAINTS:
                session.run(stmt)
            for stmt in schema.INDEXES:
                try:
                    session.run(stmt)
                except Exception:
                    pass

    def clear(self) -> None:
        with self.driver.session() as session:
            session.run(schema.CLEAR_GRAPH)

    def run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        with self.driver.session() as session:
            result = session.run(query, **params)
            return [record.data() for record in result]

    def merge_entity(
        self, qualified_name: str, label: str, props: dict[str, Any], repo: str
    ) -> None:
        query = schema.MERGE_ENTITY % {"label": label}
        self.run(query, repo=repo, qualified_name=qualified_name, props=props)

    def merge_relationship(
        self,
        source_qname: str,
        target_qname: str,
        rel_type: str,
        props: dict[str, Any] | None = None,
        allow_unresolved: bool = True,
        repo: str | None = None,
    ) -> None:
        # rel_type is interpolated into Cypher; gate it against the allow-list so a
        # tool/contract can never smuggle an arbitrary clause into the query.
        if rel_type not in schema.MERGEABLE_REL_TYPES:
            raise ValueError(
                f"rel_type {rel_type!r} is not in MERGEABLE_REL_TYPES "
                f"{sorted(schema.MERGEABLE_REL_TYPES)}"
            )
        template = schema.MERGE_RELATIONSHIP_TO_UNRESOLVED if allow_unresolved else schema.MERGE_RELATIONSHIP
        query = template % {"rel_type": rel_type}
        self.run(
            query, repo=repo, source_qname=source_qname,
            target_qname=target_qname, props=props or {},
        )

    def merge_author(self, name: str, email: str, commit_count: int) -> None:
        self.run(schema.MERGE_AUTHOR, name=name, email=email, commit_count=commit_count)

    def merge_authored_by(self, file_path: str, email: str, rank: int) -> None:
        self.run(schema.MERGE_AUTHORED_BY, file_path=file_path, email=email, rank=rank)

    def merge_co_change(
        self, qname_a: str, qname_b: str, times: int, confidence: float
    ) -> None:
        self.run(
            schema.MERGE_CO_CHANGE,
            qname_a=qname_a,
            qname_b=qname_b,
            times=times,
            confidence=confidence,
        )

    def save_manifest(self, slug: str, manifest: dict[str, str]) -> None:
        """Persist a content-hash manifest (path -> source_hash) for a repo,
        serialized as JSON on the Repository node. Used by IncrementalIngester."""
        self.run(schema.SAVE_MANIFEST, slug=slug, manifest_json=json.dumps(manifest))

    def load_manifest(self, slug: str) -> dict[str, str]:
        """Load a previously saved manifest; empty dict if none exists yet."""
        rows = self.run(schema.LOAD_MANIFEST, slug=slug)
        if not rows or not rows[0].get("manifest_json"):
            return {}
        return json.loads(rows[0]["manifest_json"])

    def stats(self) -> dict[str, int]:
        node_count = self.run("MATCH (n) RETURN count(n) AS count")[0]["count"]
        rel_count = self.run("MATCH ()-[r]->() RETURN count(r) AS count")[0]["count"]
        return {"nodes": node_count, "relationships": rel_count}
