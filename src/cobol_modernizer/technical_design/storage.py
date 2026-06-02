"""Persist TechnicalDesigns as versioned :TechnicalDesign nodes off :Repository{slug}.
Property names (services_json/version) match controlplane.build._technical_design_brief."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from cobol_modernizer.technical_design.schema import TechnicalDesign

_SAVE = """
MATCH (r:Repository {slug: $repo_slug})
OPTIONAL MATCH (r)-[:HAS_TECHNICAL_DESIGN]->(prev:TechnicalDesign)
WITH r, coalesce(max(prev.version), 0) + 1 AS version
CREATE (t:TechnicalDesign {
    id: $id, repo_slug: $repo_slug, version: version,
    services_json: $services_json, evidence_map: $evidence_map,
    html: $html, model: $model, token_usage: $token_usage, created_at: $created_at
})
CREATE (r)-[:HAS_TECHNICAL_DESIGN]->(t)
RETURN t.version AS version
"""

_LATEST = """
MATCH (r:Repository {slug: $repo_slug})-[:HAS_TECHNICAL_DESIGN]->(t:TechnicalDesign)
RETURN t ORDER BY t.version DESC LIMIT 1
"""


class TechnicalDesignStorage:
    def __init__(self, client: Any) -> None:
        self.client = client

    def save(self, design: TechnicalDesign, *, html: str, model: str = "",
             token_usage: dict[str, int] | None = None) -> TechnicalDesign:
        tid = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()
        rows = self.client.run(
            _SAVE, id=tid, repo_slug=design.repo_slug,
            services_json=json.dumps([s.model_dump(mode="json") for s in design.services]),
            evidence_map=json.dumps(design.evidence_map), html=html, model=model,
            token_usage=json.dumps(token_usage or {}), created_at=created)
        if not rows:
            raise ValueError(f"Repository not found: {design.repo_slug}")
        design.version = rows[0]["version"]
        return design

    def get_latest(self, repo_slug: str) -> dict | None:
        rows = self.client.run(_LATEST, repo_slug=repo_slug)
        return rows[0]["t"] if rows else None
