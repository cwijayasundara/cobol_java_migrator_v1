from __future__ import annotations

import asyncio
import logging

from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.agent.enrich_schema import EnrichmentTags, enrichment_tags_schema
from cobol_modernizer.agent.graph_tools import GRAPH_TOOL_NAMES, build_graph_server
from cobol_modernizer.agent.harness import AgentRunner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache-key helpers — bump ENRICH_PROMPT_VERSION whenever ENRICH_SYSTEM changes
# so that nodes are re-enriched even if their source is identical.
# ---------------------------------------------------------------------------

ENRICH_PROMPT_VERSION = "1"   # bump when ENRICH_SYSTEM changes; invalidates cache


def enrichment_cache_key(*, source_hash: str, prompt_version: str) -> str:
    return f"{source_hash}:{prompt_version}"


def should_enrich(node: dict, *, source_hash: str) -> bool:
    """Skip (return False) only when the node was already enriched against the
    current source_hash AND the current prompt version — re-pays 0 LLM cost."""
    want = enrichment_cache_key(source_hash=source_hash,
                                prompt_version=ENRICH_PROMPT_VERSION)
    return node.get("enrich_cache_key") != want


# ---------------------------------------------------------------------------
# Enrichment prompts and Cypher
# ---------------------------------------------------------------------------

ENRICH_SYSTEM = """You tag ONE code entity with its architectural role. You have
graph-navigation tools: get_entity, neighbors (CALLS/IMPORTS/CONTAINS/INHERITS),
get_source_slice (reads just this entity's lines). Inspect how the entity is USED —
not just its signature — then emit EnrichmentTags JSON:
- patterns: design patterns it participates in (e.g. Repository, Factory, State Machine)
- layer: one of presentation | business_logic | data_access | infrastructure | orchestration | domain_model
- concepts: domain concepts it represents
- summary: one plain-English sentence of what it does."""

_FETCH_UNTAGGED = """
MATCH (e:CodeEntity {repo: $repo})
WHERE e.kind IN ['Class', 'Function', 'Method', 'Module']
  AND e.semantic_layer IS NULL
  AND NOT e.qualified_name IN $seen
  AND (e.enrich_cache_key IS NULL OR e.enrich_cache_key <> $cache_key)
OPTIONAL MATCH (e)-[r]-()
WITH e, count(r) AS degree
RETURN e.qualified_name AS qualified_name, e.kind AS kind,
       e.signature AS signature, e.file_path AS file_path,
       e.enrich_cache_key AS enrich_cache_key
ORDER BY degree DESC
LIMIT $limit
"""

_WRITE_BACK = """
MATCH (e:CodeEntity {repo: $repo, qualified_name: $qname})
SET e.semantic_patterns = $patterns
SET e.semantic_layer = $layer
SET e.semantic_concepts = $concepts
SET e.semantic_summary = $summary
SET e.enrich_cache_key = $cache_key
"""


def _enrich_prompt(entity: dict) -> str:
    return (f"Entity: {entity.get('qualified_name')}\n"
            f"Kind: {entity.get('kind')}\n"
            f"File: {entity.get('file_path')}\n"
            f"Signature: {entity.get('signature') or 'N/A'}\n\n"
            "Inspect it via the tools and emit its EnrichmentTags.")


def _fetch_untagged(deps: GraphDeps, limit: int, seen: set[str],
                    source_hash: str) -> list[dict]:
    cache_key = enrichment_cache_key(source_hash=source_hash,
                                     prompt_version=ENRICH_PROMPT_VERSION)
    return deps.client.run(_FETCH_UNTAGGED, repo=deps.repo_id, limit=limit,
                           seen=list(seen), cache_key=cache_key)


async def _enrich_one(deps, runner, server, model, max_turns, entity, sem,
                      source_hash: str) -> bool:
    try:
        async with sem:
            raw = await runner.run_structured(
                system=ENRICH_SYSTEM, prompt=_enrich_prompt(entity),
                server=server, allowed_tools=GRAPH_TOOL_NAMES, model=model,
                max_turns=max_turns, schema=enrichment_tags_schema(),
            )
        if not raw:                       # SDK error path returns {} -> retry next run
            return False
        tags = EnrichmentTags.model_validate(raw)
        cache_key = enrichment_cache_key(source_hash=source_hash,
                                         prompt_version=ENRICH_PROMPT_VERSION)
        deps.client.run(
            _WRITE_BACK, repo=deps.repo_id, qname=entity["qualified_name"],
            patterns=tags.patterns, layer=tags.layer,
            concepts=tags.concepts, summary=tags.summary,
            cache_key=cache_key,
        )
        return True
    except Exception:
        logger.exception("enrichment failed for %s", entity.get("qualified_name"))
        return False


async def aenrich(deps: GraphDeps, *, runner: AgentRunner, model: str,
                  source_hash: str = "", batch_size: int = 20,
                  max_concurrency: int = 6, max_turns: int = 4) -> int:
    """Enrich every untagged entity in the repo, highest graph-centrality first,
    fanning out within each batch and looping until none remain. Returns the count
    successfully tagged.

    Nodes whose ``enrich_cache_key`` already matches the current
    ``source_hash + ENRICH_PROMPT_VERSION`` are skipped — zero LLM cost."""
    server = build_graph_server(deps)
    sem = asyncio.Semaphore(max_concurrency)
    seen: set[str] = set()
    total = 0
    while True:
        batch = _fetch_untagged(deps, batch_size, seen, source_hash)
        fresh = [e for e in batch
                 if e.get("qualified_name") and e["qualified_name"] not in seen
                 and should_enrich(e, source_hash=source_hash)]
        if not fresh:
            break
        for e in fresh:
            seen.add(e["qualified_name"])
        results = await asyncio.gather(*[
            _enrich_one(deps, runner, server, model, max_turns, e, sem,
                        source_hash) for e in fresh
        ])
        total += sum(1 for ok in results if ok)
    return total


def enrich_repo_sync(repo_id: str, *, client=None, repo_path=None,
                     model: str | None = None, source_hash: str = "",
                     batch_size: int = 20, max_concurrency: int = 6,
                     max_turns: int = 4) -> int:
    """Sync entry point for the CLI. Resolves deps + model, runs the async loop."""
    from pathlib import Path
    from cobol_modernizer.agent.harness import SdkAgentRunner
    from cobol_modernizer.cost.tiering import resolve_model

    if client is None:
        from cobol_modernizer.neo4j_client import Neo4jClient
        client = Neo4jClient()
    if repo_path is None:
        from cobol_modernizer.repo_manager import RepoManager
        repo = RepoManager(client).get(repo_id)
        if repo is None or not repo.get("local_path"):
            raise ValueError(f"Repo {repo_id} not registered or missing local_path")
        repo_path = repo["local_path"]
    model = model or resolve_model("enrichment")
    deps = GraphDeps(client=client, repo_id=repo_id, repo_path=Path(repo_path))
    runner = SdkAgentRunner()
    return asyncio.run(aenrich(deps, runner=runner, model=model,
                               source_hash=source_hash,
                               batch_size=batch_size,
                               max_concurrency=max_concurrency,
                               max_turns=max_turns))
