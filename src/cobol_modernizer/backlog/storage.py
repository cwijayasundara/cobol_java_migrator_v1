"""Persist Backlogs to Neo4j as versioned :Backlog nodes off :Repository{slug},
mirroring DomainDesignStorage. Property names (epics_json/stories_json/version) match
controlplane.build._backlog_brief so the codegen brief reads them with no change."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from cobol_modernizer.backlog.schema import Backlog

_SAVE = """
MATCH (r:Repository {slug: $repo_slug})
OPTIONAL MATCH (r)-[:HAS_BACKLOG]->(prev:Backlog)
WITH r, coalesce(max(prev.version), 0) + 1 AS version
CREATE (b:Backlog {
    id: $id, repo_slug: $repo_slug, version: version,
    epics_json: $epics_json, stories_json: $stories_json,
    evidence_map: $evidence_map, coverage_json: $coverage_json,
    html: $html, model: $model, token_usage: $token_usage, created_at: $created_at
})
CREATE (r)-[:HAS_BACKLOG]->(b)
RETURN b.version AS version
"""

_LATEST = """
MATCH (r:Repository {slug: $repo_slug})-[:HAS_BACKLOG]->(b:Backlog)
RETURN b ORDER BY b.version DESC LIMIT 1
"""


class BacklogStorage:
    def __init__(self, client: Any) -> None:
        self.client = client

    def save(self, backlog: Backlog, *, coverage: dict, html: str, model: str = "",
             token_usage: dict[str, int] | None = None) -> Backlog:
        bid = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()
        rows = self.client.run(
            _SAVE, id=bid, repo_slug=backlog.repo_slug,
            epics_json=json.dumps([e.model_dump(mode="json") for e in backlog.epics]),
            stories_json=json.dumps([s.model_dump(mode="json") for s in backlog.stories]),
            evidence_map=json.dumps(backlog.evidence_map),
            coverage_json=json.dumps(coverage or {}), html=html, model=model,
            token_usage=json.dumps(token_usage or {}), created_at=created)
        if not rows:
            raise ValueError(f"Repository not found: {backlog.repo_slug}")
        backlog.version = rows[0]["version"]
        return backlog

    def get_latest(self, repo_slug: str) -> dict | None:
        rows = self.client.run(_LATEST, repo_slug=repo_slug)
        return rows[0]["b"] if rows else None
