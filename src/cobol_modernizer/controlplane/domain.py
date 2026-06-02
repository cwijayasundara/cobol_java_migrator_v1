"""Persist Domain Designs to Neo4j (versioned :DomainDesign nodes off :Repository{slug}),
mirroring brd.storage.BRDStorage. The GET path reads the latest persisted node so a finished
design survives a server restart (the JobRunner only tracks in-flight progress)."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from cobol_modernizer.domain.assemble import assemble
from cobol_modernizer.domain.decompose import decompose
from cobol_modernizer.domain.schema import DomainDesign
from cobol_modernizer.domain.tactical import design_all_contexts
from cobol_modernizer.seam.signals import raw_signals_for_program

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
            token_usage=json.dumps(token_usage or {}), created_at=created)
        if not rows:
            raise ValueError(f"Repository not found: {dd.repo_slug}")
        dd.version = rows[0]["version"]
        return dd

    def get_latest(self, repo_slug: str) -> dict | None:
        rows = self.client.run(_LATEST, repo_slug=repo_slug)
        return rows[0]["d"] if rows else None


def run_domain_design(client: Any, repo_slug: str, *, brd_text: str, runner: Any,
                      model: str, timeout_s: float, signals_fn=raw_signals_for_program,
                      version: int = 0) -> DomainDesign:
    """Phases 1-3, synchronous wrapper (drives the async agents via asyncio.run).
    Does NOT persist — the caller persists so it can inject storage/version."""
    async def _go() -> DomainDesign:
        dm = await decompose(client, repo_slug, brd_text=brd_text, runner=runner,
                             model=model, timeout_s=timeout_s, signals_fn=signals_fn)
        known = {r["q"] for r in client.run(
            "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q", repo=repo_slug)}
        designs = await design_all_contexts(dm.contexts, known_refs=known, runner=runner,
                                            model=model, timeout_s=timeout_s)
        return assemble(repo_slug, dm, designs, version=version)
    return asyncio.run(_go())
