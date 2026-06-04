"""Persist Domain Designs to Neo4j (versioned :DomainDesign nodes off :Repository{slug}),
mirroring brd.storage.BRDStorage. The GET path reads the latest persisted node so a finished
design survives a server restart (the JobRunner only tracks in-flight progress)."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from cobol_modernizer.agent.context_pack import (
    ContextPack,
    build_context_pack,
    build_domain_decomposition_pack,
    build_domain_tactical_pack,
)
from cobol_modernizer.domain.assemble import assemble
from cobol_modernizer.domain.decompose import decompose
from cobol_modernizer.domain.deterministic import generate_deterministic_domain_design
from cobol_modernizer.domain.schema import DomainDesign
from cobol_modernizer.domain.schema import ContextDesign, DecompositionMap
from cobol_modernizer.domain.tactical import design_all_contexts
from cobol_modernizer.domain.tactical import (
    design_context,
    generate_aggregate_payload,
    generate_contract_payload,
    generate_mapping_payload,
    _merge_raw_parts,
    _parse as _parse_context_design,
)
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _pack_for_decomposition(*, repo_slug: str, brd_text: str,
                            backlog_json: str) -> ContextPack:
    return build_domain_decomposition_pack(
        repo_slug=repo_slug, brd_text=brd_text, backlog_json=backlog_json)


def _pack_for_tactical_unit(*, unit_type: str, unit_key: str,
                            context: dict[str, Any], known_refs: set[str],
                            aggregate: dict | None = None,
                            contract: dict | None = None) -> ContextPack:
    return build_domain_tactical_pack(
        unit_type=unit_type, unit_key=unit_key, context=context,
        known_refs=known_refs, aggregate=aggregate, contract=contract)


def _use_deterministic_domain() -> bool:
    mode = os.environ.get("DOMAIN_DESIGN_MODE", "auto").strip().lower()
    if mode in {"llm", "agent"}:
        return False
    if mode in {"deterministic", "fast"}:
        return True
    flag = os.environ.get("DOMAIN_DETERMINISTIC_FIRST", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _pack_for_deterministic_domain(*, repo_slug: str, brd_text: str,
                                   backlog_json: str) -> ContextPack:
    return build_context_pack(
        stage="domain-design", unit_type="deterministic", unit_key="domain-design",
        sections=[
            {"title": "BRD", "content": brd_text},
            {"title": "Backlog", "content": backlog_json, "required": False},
        ],
        metadata={"repo_slug": repo_slug},
        prompt_version="domain-deterministic-v1")


def _cached_payload(ledger: Any, *, workspace_id: str | None, stage: str,
                    unit_type: str, unit_key: str, input_hash: str) -> dict | None:
    if ledger is None or workspace_id is None:
        return None
    unit = ledger.find_cached_work_unit(
        workspace_id=workspace_id, stage=stage, unit_type=unit_type,
        unit_key=unit_key, input_hash=input_hash)
    return dict(unit.payload) if unit is not None else None


def _create_unit(ledger: Any, *, workspace_id: str | None, repo_slug: str,
                 stage: str, unit_type: str, unit_key: str, input_hash: str,
                 agent_run_id: str | None, model: str, timeout_s: float,
                 max_turns: int | None = None):
    if ledger is None or workspace_id is None:
        return None
    return ledger.create_work_unit(
        workspace_id=workspace_id, repo_slug=repo_slug, stage=stage,
        unit_type=unit_type, unit_key=unit_key, input_hash=input_hash,
        agent_run_id=agent_run_id, model=model, timeout_s=timeout_s,
        max_turns=max_turns)


async def _decompose_with_ledger(client: Any, repo_slug: str, *, brd_text: str,
                                 runner: Any, model: str, timeout_s: float,
                                 signals_fn, backlog_json: str,
                                 ledger: Any, workspace_id: str | None,
                                 agent_run_id: str | None) -> DecompositionMap:
    pack = _pack_for_decomposition(
        repo_slug=repo_slug, brd_text=brd_text, backlog_json=backlog_json)
    input_hash = pack.input_hash
    cached = _cached_payload(
        ledger, workspace_id=workspace_id, stage="domain-design",
        unit_type="decomposition", unit_key="decompose", input_hash=input_hash)
    if cached is not None:
        return DecompositionMap.model_validate(cached)

    unit = _create_unit(
        ledger, workspace_id=workspace_id, repo_slug=repo_slug,
        stage="domain-design", unit_type="decomposition", unit_key="decompose",
        input_hash=input_hash, agent_run_id=agent_run_id, model=model,
        timeout_s=timeout_s)
    if unit is not None:
        ledger.mark_work_unit_running(unit.id, model=model, timeout_s=timeout_s)
    try:
        dm = await decompose(client, repo_slug, brd_text=brd_text, runner=runner,
                             model=model, timeout_s=timeout_s,
                             signals_fn=signals_fn, backlog_json=backlog_json)
    except Exception as exc:
        if unit is not None:
            ledger.mark_work_unit_failed(unit.id, error_cause=f"{type(exc).__name__}: {exc}")
        raise
    if unit is not None:
        ledger.mark_work_unit_succeeded(
            unit.id, payload=dm.model_dump(mode="json"),
            token_usage=dict(getattr(runner, "token_usage", {}) or {}),
            cost_usd=float(getattr(runner, "cost_usd", 0.0) or 0.0))
    return dm


async def _design_contexts_with_ledger(contexts, *, known_refs: set[str], runner: Any,
                                       model: str, timeout_s: float, ledger: Any,
                                       workspace_id: str | None, repo_slug: str,
                                       agent_run_id: str | None) -> list[ContextDesign]:
    if ledger is None or workspace_id is None:
        return await design_all_contexts(contexts, known_refs=known_refs, runner=runner,
                                         model=model, timeout_s=timeout_s)
    semaphore = asyncio.Semaphore(max(1, _env_int("DOMAIN_TACTICAL_MAX_CONCURRENCY", 2)))

    async def _payload_unit(*, ctx, unit_type: str, unit_key: str, pack: ContextPack,
                            producer):
        input_hash = pack.input_hash
        cached = _cached_payload(
            ledger, workspace_id=workspace_id, stage="domain-design",
            unit_type=unit_type, unit_key=unit_key, input_hash=input_hash)
        if cached is not None:
            return cached

        unit = _create_unit(
            ledger, workspace_id=workspace_id, repo_slug=repo_slug,
            stage="domain-design", unit_type=unit_type,
            unit_key=unit_key, input_hash=input_hash, agent_run_id=agent_run_id,
            model=model, timeout_s=timeout_s)
        if unit is not None:
            ledger.mark_work_unit_running(unit.id, model=model, timeout_s=timeout_s)
        try:
            payload = await producer()
        except Exception as exc:
            if unit is not None:
                ledger.mark_work_unit_failed(unit.id, error_cause=f"{type(exc).__name__}: {exc}")
            raise
        if unit is not None:
            ledger.mark_work_unit_succeeded(
                unit.id, payload=payload,
                token_usage=dict(getattr(runner, "token_usage", {}) or {}),
                cost_usd=float(getattr(runner, "cost_usd", 0.0) or 0.0))
        return payload

    async def _one(ctx) -> ContextDesign:
        async with semaphore:
            ctx_payload = ctx.model_dump(mode="json")
            aggregate_pack = _pack_for_tactical_unit(
                unit_type="tactical-aggregate", unit_key=ctx.name,
                context=ctx_payload, known_refs=known_refs)
            aggregate = await _payload_unit(
                ctx=ctx, unit_type="tactical-aggregate", unit_key=ctx.name,
                pack=aggregate_pack,
                producer=lambda: generate_aggregate_payload(
                    ctx, runner=runner, model=model, timeout_s=timeout_s))
            contract_pack = _pack_for_tactical_unit(
                unit_type="tactical-contract", unit_key=ctx.name,
                context=ctx_payload, known_refs=known_refs, aggregate=aggregate)
            contract = await _payload_unit(
                ctx=ctx, unit_type="tactical-contract", unit_key=ctx.name,
                pack=contract_pack,
                producer=lambda: generate_contract_payload(
                    ctx, aggregate_payload=aggregate, runner=runner, model=model,
                    timeout_s=timeout_s))
            mapping_pack = _pack_for_tactical_unit(
                unit_type="tactical-mapping", unit_key=ctx.name,
                context=ctx_payload, known_refs=known_refs, aggregate=aggregate,
                contract=contract)
            mapping = await _payload_unit(
                ctx=ctx, unit_type="tactical-mapping", unit_key=ctx.name,
                pack=mapping_pack,
                producer=lambda: generate_mapping_payload(
                    ctx, aggregate_payload=aggregate, contract_payload=contract,
                    runner=runner, model=model, timeout_s=timeout_s))
        raw = _merge_raw_parts(aggregate=aggregate, contract=contract, mapping=mapping)
        return _parse_context_design(raw, ctx, known_refs)

    results = await asyncio.gather(*[_one(c) for c in contexts], return_exceptions=True)
    return [r for r in results if isinstance(r, ContextDesign)]


def run_domain_design(client: Any, repo_slug: str, *, brd_text: str, runner: Any,
                      model: str, timeout_s: float, signals_fn=raw_signals_for_program,
                      version: int = 0, backlog_json: str = "",
                      ledger: Any = None, workspace_id: str | None = None,
                      agent_run_id: str | None = None) -> DomainDesign:
    """Phases 1-3, synchronous wrapper (drives the async agents via asyncio.run).
    Does NOT persist — the caller persists so it can inject storage/version."""
    if _use_deterministic_domain():
        pack = _pack_for_deterministic_domain(
            repo_slug=repo_slug, brd_text=brd_text, backlog_json=backlog_json)
        cached = _cached_payload(
            ledger, workspace_id=workspace_id, stage="domain-design",
            unit_type="deterministic", unit_key="domain-design",
            input_hash=pack.input_hash)
        if cached is not None:
            return DomainDesign.model_validate(cached)
        unit = _create_unit(
            ledger, workspace_id=workspace_id, repo_slug=repo_slug,
            stage="domain-design", unit_type="deterministic",
            unit_key="domain-design", input_hash=pack.input_hash,
            agent_run_id=agent_run_id, model="deterministic", timeout_s=0.0,
            max_turns=0)
        if unit is not None:
            ledger.mark_work_unit_running(
                unit.id, model="deterministic", timeout_s=0.0, max_turns=0)
        try:
            dd = generate_deterministic_domain_design(
                client, repo_slug, brd_text=brd_text,
                backlog_json=backlog_json, version=version)
        except Exception as exc:
            if unit is not None:
                ledger.mark_work_unit_failed(unit.id, error_cause=f"{type(exc).__name__}: {exc}")
            raise
        if unit is not None:
            ledger.mark_work_unit_succeeded(
                unit.id, payload=dd.model_dump(mode="json"),
                token_usage={"input": 0, "output": 0, "cache_read": 0,
                             "cache_creation": 0},
                cost_usd=0.0)
        return dd

    async def _go() -> DomainDesign:
        dm = await _decompose_with_ledger(
            client, repo_slug, brd_text=brd_text, runner=runner,
            model=model, timeout_s=timeout_s, signals_fn=signals_fn,
            backlog_json=backlog_json, ledger=ledger, workspace_id=workspace_id,
            agent_run_id=agent_run_id)
        known = {r["q"] for r in client.run(
            "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q", repo=repo_slug)}
        designs = await _design_contexts_with_ledger(
            dm.contexts, known_refs=known, runner=runner, model=model,
            timeout_s=timeout_s, ledger=ledger, workspace_id=workspace_id,
            repo_slug=repo_slug, agent_run_id=agent_run_id)
        return assemble(repo_slug, dm, designs, version=version)
    return asyncio.run(_go())
