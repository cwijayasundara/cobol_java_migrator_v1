"""Persist Domain Designs to Neo4j (versioned :DomainDesign nodes off :Repository{slug}),
mirroring brd.storage.BRDStorage. The GET path reads the latest persisted node so a finished
design survives a server restart (the JobRunner only tracks in-flight progress)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from cobol_modernizer.domain.schema import DomainDesign

_SAVE = """
MATCH (r:Repository {slug: $repo_slug})
OPTIONAL MATCH (r)-[:HAS_DOMAIN_DESIGN]->(prev:DomainDesign)
WITH r, coalesce(max(prev.version), 0) + 1 AS version
CREATE (d:DomainDesign {
    id: $id, repo_slug: $repo_slug, version: version, rating: $rating,
    weighted_score: $weighted_score, contexts_json: $contexts_json,
    designs_json: $designs_json, evidence_map: $evidence_map, html: $html,
    model: $model, token_usage: $token_usage, created_at: $created_at
})
CREATE (r)-[:HAS_DOMAIN_DESIGN]->(d)
RETURN d.version AS version
"""

_LATEST = """
MATCH (r:Repository {slug: $repo_slug})-[:HAS_DOMAIN_DESIGN]->(d:DomainDesign)
RETURN d ORDER BY d.version DESC LIMIT 1
"""


class DomainDesignStorage:
    def __init__(self, client: Any) -> None:
        self.client = client

    def save(self, dd: DomainDesign, *, html: str, model: str = "",
             token_usage: dict[str, int] | None = None,
             evidence_map: dict[str, list[str]] | None = None) -> DomainDesign:
        did = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()
        rows = self.client.run(
            _SAVE, id=did, repo_slug=dd.repo_slug, rating=dd.rating,
            weighted_score=dd.weighted_score,
            contexts_json=json.dumps([c.model_dump(mode="json") for c in dd.contexts]),
            designs_json=json.dumps([d.model_dump(mode="json") for d in dd.designs]),
            evidence_map=json.dumps(evidence_map or {}), html=html, model=model,
            token_usage=json.dumps(token_usage or {}), created_at=created,
            version=1)
        if not rows:
            raise ValueError(f"Repository not found: {dd.repo_slug}")
        dd.version = rows[0]["version"]
        return dd

    def get_latest(self, repo_slug: str) -> dict | None:
        rows = self.client.run(_LATEST, repo_slug=repo_slug)
        return rows[0]["d"] if rows else None
