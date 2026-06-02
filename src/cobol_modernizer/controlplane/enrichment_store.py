"""Persist LLM enrichment ("Improve") outputs — seam rationale, plan INVEST/narrative,
design narrative — to Neo4j so they survive restarts and are reused instead of re-running
the multi-minute LLM. Versioned per (repo_slug, kind), mirroring BRDStorage /
DomainDesignStorage. `payload` is the exact dict the enrich job returns; we round-trip it
verbatim as JSON so the API contract is unchanged whether the result is fresh or reused."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

_SAVE = """
MATCH (r:Repository {slug: $repo_slug})
OPTIONAL MATCH (r)-[:HAS_ENRICHMENT]->(prev:Enrichment {kind: $kind})
WITH r, coalesce(max(prev.version), 0) + 1 AS version
CREATE (e:Enrichment {id: $id, repo_slug: $repo_slug, kind: $kind, version: version,
                      payload_json: $payload_json, created_at: $created_at})
CREATE (r)-[:HAS_ENRICHMENT]->(e)
RETURN e.version AS version
"""

_LATEST = """
MATCH (r:Repository {slug: $repo_slug})-[:HAS_ENRICHMENT]->(e:Enrichment {kind: $kind})
RETURN e ORDER BY e.version DESC LIMIT 1
"""


class EnrichmentStorage:
    def __init__(self, client: Any) -> None:
        self.client = client

    def save(self, repo_slug: str, kind: str, payload: dict) -> int:
        rows = self.client.run(
            _SAVE, id=str(uuid.uuid4()), repo_slug=repo_slug, kind=kind,
            payload_json=json.dumps(payload),
            created_at=datetime.now(timezone.utc).isoformat())
        return rows[0]["version"] if rows else 0

    def get_latest(self, repo_slug: str, kind: str) -> dict | None:
        rows = self.client.run(_LATEST, repo_slug=repo_slug, kind=kind)
        if not rows:
            return None
        try:
            return json.loads(rows[0]["e"].get("payload_json") or "null")
        except Exception:  # noqa: BLE001 — malformed payload -> treat as absent
            return None
