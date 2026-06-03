"""DDD contexts + backlog stories + seam waves → target technical architecture
(services with API/persistence/integration contracts), grounded on graph refs, known
story ids, and known DDD context names. Parser drops anything ungrounded."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from cobol_modernizer.enrichment.base import (
    EnrichmentResult,
    run_batched,
    run_batched_result,
)
from cobol_modernizer.enrichment.refs import relevant_refs
from cobol_modernizer.technical_design.schema import (
    ApiContract,
    IntegrationContract,
    PersistenceDesign,
    TechnicalDesign,
    TechnicalService,
)

TECHNICAL_DESIGN_SYSTEM = (
    "You transform a DDD bounded-context model, a business backlog, and seam delivery "
    "waves into a target technical architecture for a Spring Boot system. Define one "
    "service per bounded context. Each service cites the story ids it delivers and the "
    "graph evidence refs it derives from. Specify API contracts, persistence access "
    "patterns, and integration contracts. Use access_pattern only for the enum "
    "legacy-mimic, repository, event-sourced, or read-replica; put COBOL-specific "
    "read/write semantics, transaction boundaries, file-status rules, and source refs "
    "in details. Do not invent story ids, context names, or graph refs — use only the "
    "ones provided."
)

logger = logging.getLogger(__name__)

_ACCESS_PATTERNS = {"legacy-mimic", "repository", "event-sourced", "read-replica"}
_STYLES = {"sync", "async", "batch"}
_DEPLOYMENTS = {"module", "microservice"}

TECHNICAL_DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "services": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "bounded_context": {"type": "string"},
                    "deployment": {"type": "string", "enum": ["module", "microservice"]},
                    "story_ids": {"type": "array", "items": {"type": "string"}},
                    "api_contracts": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "method": {"type": "string"},
                                       "path": {"type": "string"},
                                       "request_model": {"type": "string"},
                                       "response_model": {"type": "string"},
                                       "details": {"type": "string"}},
                        "required": ["name", "method", "path"]}},
                    "persistence": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"resource": {"type": "string"},
                                       "access_pattern": {"type": "string", "enum": [
                                           "legacy-mimic", "repository", "event-sourced",
                                           "read-replica"]},
                                       "owner_service": {"type": "string"},
                                       "details": {"type": "string"}},
                        "required": ["resource", "access_pattern"]}},
                    "integrations": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "style": {"type": "string"},
                                       "target": {"type": "string"}, "payload": {"type": "string"}},
                        "required": ["name", "style", "target"]}},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "bounded_context", "deployment"],
            },
        },
    },
    "required": ["services"],
}


def build_technical_design_prompt(*, ddd_json: str, backlog_json: str,
                                  seam_waves_json: str, graph_summary: dict) -> str:
    return (
        "## DDD bounded contexts\n```json\n" + ddd_json + "\n```\n"
        "## Business backlog (stories)\n```json\n" + backlog_json + "\n```\n"
        "## Seam delivery waves (cutover order)\n```json\n" + seam_waves_json + "\n```\n"
        "## Graph coupling summary\n```json\n" + json.dumps(graph_summary) + "\n```\n"
        "Produce one technical service per bounded context with API, persistence, and "
        "integration contracts. Every writer resource must be owned by exactly one service. "
        "For persistence, keep access_pattern to the allowed enum and put detailed COBOL "
        "semantics in details."
    )


def _ground(values: Any, allowed: set[str]) -> list[str]:
    out: list[str] = []
    for v in values or []:
        if isinstance(v, str) and v in allowed and v not in out:
            out.append(v)
    return out


def _slug(value: Any, *, fallback: str = "service") -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip()).strip("-").lower()
    return text or fallback


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def fallback_technical_design_payload(*, contexts: list[dict[str, Any]],
                                      stories: list[dict[str, Any]],
                                      seam_waves: list[list[str]],
                                      known_refs: set[str]) -> dict:
    """Build a conservative technical design without another model call.

    The fallback preserves one-service-per-context and only cites graph refs that
    already exist. It is deliberately simple so it can run after LLM billing,
    timeout, or turn-cap failures and keep the migration workflow moving.
    """
    if not contexts:
        return {"services": []}

    wave_refs = [ref for wave in seam_waves for ref in _as_list(wave) if isinstance(ref, str)]
    services: list[dict[str, Any]] = []
    single_context = len(contexts) == 1

    for ctx in contexts:
        if not isinstance(ctx, dict) or not ctx.get("name"):
            continue
        ctx_name = str(ctx["name"])
        svc_name = f"{_slug(ctx_name)}-service"
        ctx_refs = [r for r in _as_list(ctx.get("member_programs")) if isinstance(r, str)]
        ctx_refs += [r for r in _as_list(ctx.get("cited_refs")) if isinstance(r, str)]
        if single_context:
            ctx_refs += wave_refs
        evidence_refs = _ground(ctx_refs, known_refs)

        story_ids: list[str] = []
        for story in stories:
            if not isinstance(story, dict) or not story.get("id"):
                continue
            story_ctx = story.get("context") or story.get("bounded_context")
            story_refs = set(r for r in _as_list(story.get("evidence_refs")) if isinstance(r, str))
            if story_ctx == ctx_name or (story_refs and story_refs.intersection(evidence_refs)):
                story_ids.append(str(story["id"]))
            elif single_context and not story_ctx:
                story_ids.append(str(story["id"]))

        topology = ctx.get("topology") if isinstance(ctx.get("topology"), dict) else {}
        deployment = topology.get("deployment") or ctx.get("deployment") or "module"
        if deployment not in _DEPLOYMENTS:
            deployment = "module"

        resources = [r for r in _as_list(ctx.get("owned_resources")) if isinstance(r, str)]
        persistence = [
            {"resource": resource, "access_pattern": "legacy-mimic", "owner_service": svc_name}
            for resource in resources
        ]

        api_contracts = [{
            "name": f"{_slug(ctx_name)}-command",
            "method": "POST",
            "path": f"/api/{_slug(ctx_name)}",
            "request_model": f"{re.sub(r'[^A-Za-z0-9]', '', ctx_name)}Request",
            "response_model": f"{re.sub(r'[^A-Za-z0-9]', '', ctx_name)}Response",
            "details": "Command endpoint generated from the bounded-context boundary.",
        }]

        integrations: list[dict[str, str]] = []
        for dep in _as_list(ctx.get("depends_on")):
            if not isinstance(dep, dict) or not dep.get("target"):
                continue
            style = dep.get("style") if dep.get("style") in _STYLES else "sync"
            target = str(dep["target"])
            integrations.append({
                "name": f"{_slug(ctx_name)}-to-{_slug(target)}",
                "style": style,
                "target": target,
                "payload": str(dep.get("payload", "")),
            })

        services.append({
            "name": svc_name,
            "bounded_context": ctx_name,
            "deployment": deployment,
            "story_ids": story_ids,
            "api_contracts": api_contracts,
            "persistence": persistence,
            "integrations": integrations,
            "evidence_refs": evidence_refs,
        })
    return {"services": services}


def _coerce_access_pattern(value: Any, *, service: Any) -> str:
    if value in _ACCESS_PATTERNS:
        return value
    if value:  # present but out-of-enum
        logger.warning("technical-design: coerced access_pattern %r -> 'legacy-mimic' "
                       "for service %r", value, service)
    return "legacy-mimic"


def _persistence_details(item: dict[str, Any], *, access_pattern: Any) -> str:
    detail = item.get("details")
    if isinstance(detail, str) and detail.strip():
        return detail
    if isinstance(access_pattern, str) and access_pattern not in _ACCESS_PATTERNS:
        return access_pattern
    return ""


def _coerce_style(value: Any, *, service: Any) -> str:
    if value in _STYLES:
        return value
    if value:  # present but out-of-enum
        logger.warning("technical-design: coerced style %r -> 'sync' for service %r",
                       value, service)
    return "sync"


def parse_technical_design_payload(raw: dict, *, repo_slug: str, known_refs: set[str],
                                   known_story_ids: set[str],
                                   known_contexts: set[str]) -> TechnicalDesign:
    services: list[TechnicalService] = []
    for item in raw.get("services", []):
        if not isinstance(item, dict):
            continue
        ctx = str(item.get("bounded_context", ""))
        # known_contexts is empty only before a DDD design exists; the Task 10 caller
        # guarantees one, so this guard is effectively always active. Empty-set => no
        # filtering (lenient bootstrap).
        if known_contexts and ctx not in known_contexts:
            continue  # drop services not tied to a known DDD context
        svc_name = item.get("name")
        deployment = item.get("deployment")
        if deployment not in _DEPLOYMENTS:
            if deployment:  # present but out-of-enum
                logger.warning("technical-design: coerced deployment %r -> 'module' "
                               "for service %r", deployment, svc_name)
            deployment = "module"
        apis = [ApiContract(name=str(a.get("name", "")), method=str(a.get("method", "")),
                            path=str(a.get("path", "")),
                            request_model=str(a.get("request_model", "")),
                            response_model=str(a.get("response_model", "")),
                            details=str(a.get("details", "")))
                for a in item.get("api_contracts", []) if isinstance(a, dict)]
        persistence = [
            PersistenceDesign(
                resource=str(p.get("resource", "")),
                access_pattern=_coerce_access_pattern(p.get("access_pattern"),
                                                      service=svc_name),
                owner_service=str(p.get("owner_service", "")),
                details=_persistence_details(p, access_pattern=p.get("access_pattern")),
            )
            for p in item.get("persistence", []) if isinstance(p, dict)
        ]
        integrations = [IntegrationContract(name=str(i.get("name", "")),
                                            style=_coerce_style(i.get("style"), service=svc_name),
                                            target=str(i.get("target", "")),
                                            payload=str(i.get("payload", "")))
                        for i in item.get("integrations", []) if isinstance(i, dict)]
        services.append(TechnicalService(
            name=str(item.get("name", "")), bounded_context=ctx, deployment=deployment,
            story_ids=_ground(item.get("story_ids"), known_story_ids),
            api_contracts=apis, persistence=persistence, integrations=integrations,
            evidence_refs=_ground(item.get("evidence_refs"), known_refs)))
    evidence_map = {s.name: s.evidence_refs for s in services}
    return TechnicalDesign(repo_slug=repo_slug, services=services, evidence_map=evidence_map)


async def generate_technical_design_payload(*, runner, model: str, timeout_s: float,
                                            ddd_json: str, backlog_json: str,
                                            seam_waves_json: str, graph_summary: dict,
                                            max_turns: int = 6) -> dict:
    # max_turns default 6 (not run_batched's 2): under claude-agent-sdk 0.2.87 emitting
    # the structured-output result consumes a turn, and this large DDD+backlog+seams
    # prompt needs a few reasoning turns before it — 2 reliably hits the turn cap and
    # returns {} (an empty design). Override via TECHNICAL_DESIGN_MAX_TURNS.
    prompt = build_technical_design_prompt(ddd_json=ddd_json, backlog_json=backlog_json,
                                           seam_waves_json=seam_waves_json,
                                           graph_summary=graph_summary)
    return await run_batched(runner=runner, system=TECHNICAL_DESIGN_SYSTEM, prompt=prompt,
                             schema=TECHNICAL_DESIGN_SCHEMA, model=model, timeout_s=timeout_s,
                             label="technical-design-generate", max_turns=max_turns)


# --- Classify-and-Act + Fan-Out: per-bounded-context decomposition ----------
# The single TECHNICAL_DESIGN_SCHEMA above emits ALL services in ONE call (kept for
# the size-routed one-shot path). The schema below scopes a single call to ONE
# bounded context. Because every service is parsed independently by
# `parse_technical_design_payload` (and cross-service ownership is checked AFTER the
# merge, in the gate), the merged {services: [...]} from per-context calls is
# byte-for-byte what the parser already consumes. Each per-context call inlines ONLY
# that context's lossless-relevant refs (no truncation), so a large repo never has
# to dump the whole graph into one prompt.

SERVICE_SCHEMA = {
    "type": "object",
    "properties": {
        "services": TECHNICAL_DESIGN_SCHEMA["properties"]["services"],
    },
    "required": ["services"],
}


SERVICE_SYSTEM = (
    "You transform ONE DDD bounded context (plus the business backlog and seam "
    "delivery waves) into the technical design for THAT context's service in a "
    "Spring Boot system. Emit exactly one service for the given bounded context. "
    "The service cites the story ids it delivers and the graph evidence refs it "
    "derives from. Specify API contracts, persistence access patterns, and "
    "integration contracts. Use access_pattern only for the enum legacy-mimic, "
    "repository, event-sourced, or read-replica; put COBOL-specific read/write "
    "semantics, transaction boundaries, file-status rules, and source refs in "
    "details. Do not invent story ids, context names, or graph refs — use only the "
    "ones provided."
)


def build_service_prompt(*, context: dict, backlog_json: str, seam_waves_json: str,
                         relevant_refs: list[str], known_story_ids: list[str]) -> str:
    """Prompt for the per-context service call. Scoped to ONE bounded context: only
    this context's declaration is inlined (so other contexts never leak in), plus the
    backlog, seam waves, this context's FULL relevant graph refs (no truncation), and
    the citable story ids."""
    ctx_name = str(context.get("name", ""))
    return (
        "## Bounded context (design the service for THIS context only)\n```json\n"
        + json.dumps(context) + "\n```\n"
        "## Business backlog (stories)\n```json\n" + backlog_json + "\n```\n"
        "## Seam delivery waves (cutover order)\n```json\n" + seam_waves_json + "\n```\n"
        "## Known graph evidence refs (cite only these)\n```json\n"
        + json.dumps(relevant_refs) + "\n```\n"
        "## Known story ids (cite only these)\n" + ", ".join(known_story_ids) + "\n"
        f"Produce exactly one technical service for the bounded context "
        f"\"{ctx_name}\" with API, persistence, and integration contracts. Every "
        "writer resource this service owns must be owned by exactly one service. "
        "For persistence, keep access_pattern to the allowed enum and put detailed "
        "COBOL semantics in details."
    )


async def generate_service_for_context(*, runner, model: str, timeout_s: float,
                                       max_turns: int, context: dict, backlog_json: str,
                                       seam_waves_json: str, relevant_refs: list[str],
                                       known_story_ids: list[str],
                                       attempts: int = 2,
                                       escalate: bool = True) -> EnrichmentResult:
    """MAP unit: a single bounded structured call that emits the service for ONE
    bounded context. `relevant_refs` is the lossless relevant set for THIS context
    (computed by the caller) and is inlined as-is — never truncated. Returns the
    typed result so a gating caller can surface the concrete failure cause.

    `attempts`/`escalate` are threaded into the shared `run_batched_result` retry
    primitive: a context whose call times out (or empties out at the turn cap) is
    re-issued with an ESCALATED per-context budget before being skipped — so one
    transient timeout no longer drops a whole context. `timeout_s` is the PER-CONTEXT
    budget (TECH_DESIGN_CONTEXT_TIMEOUT_S upstream), not a single outer wall."""
    prompt = build_service_prompt(
        context=context, backlog_json=backlog_json, seam_waves_json=seam_waves_json,
        relevant_refs=relevant_refs, known_story_ids=known_story_ids)
    return await run_batched_result(
        runner=runner, system=SERVICE_SYSTEM, prompt=prompt, schema=SERVICE_SCHEMA,
        model=model, timeout_s=timeout_s,
        label=f"technical-design:{context.get('name', '?')}", max_turns=max_turns,
        attempts=attempts, escalate=escalate)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _decompose(contexts: list[dict], *, mode: str | None = None) -> bool:
    """Classify-and-Act size router. Proxy = number of bounded contexts (each becomes
    one service — the unit decomposition parallelizes). TECH_DESIGN_GEN_MODE forces
    the path; in `auto`, decompose at/above TECH_DESIGN_DECOMPOSE_MIN_CONTEXTS
    (default 3)."""
    m = (mode or os.environ.get("TECH_DESIGN_GEN_MODE", "auto")).strip().lower()
    if m == "decomposed":
        return True
    if m == "oneshot":
        return False
    min_contexts = _env_int("TECH_DESIGN_DECOMPOSE_MIN_CONTEXTS", 3)
    return len([c for c in contexts if isinstance(c, dict) and c.get("name")]) >= min_contexts


async def generate_technical_design_result(*, runner, model: str, timeout_s: float,
                                           contexts: list[dict], stories: list[dict],
                                           seam_waves: list, known_refs: list[str],
                                           known_story_ids: list[str],
                                           max_turns: int = 6,
                                           mode: str | None = None) -> EnrichmentResult:
    """Size-routed technical-design generation returning the typed result.

    auto/oneshot small input -> preserved one-shot path (all services in ONE call).
    Decomposed path: fan out ONE bounded structured call per bounded context (bounded
    concurrency, partial failure tolerated), each scoped to that context's OWN lossless
    relevant refs, then merge into the {services: [...]} shape the parser consumes.
    Never caps/truncates. Fails loud (ok=False with a typed cause) only when NO context
    produced a service."""
    backlog_json = json.dumps({"stories": stories})
    seam_waves_json = json.dumps(seam_waves)
    named = [c for c in contexts if isinstance(c, dict) and c.get("name")]

    if not _decompose(contexts, mode=mode):
        # Preserved one-shot path: all services in a single structured call. Inline
        # only the BRD/DDD-relevant refs (lossless, NO cap) into the prompt; the full
        # `known_refs` stays available to the caller for grounding.
        relevant = relevant_refs(contexts, known_refs)
        prompt = build_technical_design_prompt(
            ddd_json=json.dumps({"contexts": contexts}), backlog_json=backlog_json,
            seam_waves_json=seam_waves_json, graph_summary={"refs": relevant})
        return await run_batched_result(
            runner=runner, system=TECHNICAL_DESIGN_SYSTEM, prompt=prompt,
            schema=TECHNICAL_DESIGN_SCHEMA, model=model, timeout_s=timeout_s,
            label="technical-design-generate", max_turns=max_turns)

    # PER-CONTEXT budgets, NO single outer 300s wall: each unit is bounded by its OWN
    # TECH_DESIGN_CONTEXT_TIMEOUT_S (defaulting to the passed timeout_s) and retries
    # with escalation up to TECH_DESIGN_UNIT_ATTEMPTS before being skipped. The outer
    # `asyncio.gather` below is intentionally NOT wrapped in a single asyncio wall, so a
    # slow-but-progressing multi-context run is never killed mid-flight (the JobRunner
    # lets the long job finish). A context that exhausts its attempts is dropped (its
    # service is absent from the merge), and only an ALL-contexts-fail run yields the
    # typed failure that the control plane degrades to the deterministic fallback.
    ctx_timeout_s = _env_float("TECH_DESIGN_CONTEXT_TIMEOUT_S", timeout_s)
    ctx_max_turns = _env_int("TECH_DESIGN_CONTEXT_MAX_TURNS", max_turns)
    unit_attempts = max(1, _env_int("TECH_DESIGN_UNIT_ATTEMPTS", 2))
    max_concurrency = max(1, _env_int("TECH_DESIGN_MAX_CONCURRENCY", 4))
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _one(context: dict) -> list[dict]:
        # Each context inlines ONLY its OWN lossless-relevant refs (no truncation):
        # walk the context declaration for cited known refs.
        refs = relevant_refs(context, known_refs)
        async with semaphore:
            res = await generate_service_for_context(
                runner=runner, model=model, timeout_s=ctx_timeout_s,
                max_turns=ctx_max_turns, context=context, backlog_json=backlog_json,
                seam_waves_json=seam_waves_json, relevant_refs=refs,
                known_story_ids=known_story_ids,
                attempts=unit_attempts, escalate=True)
        if not res.ok:
            logger.warning("technical-design: service call for context %s failed (%s) "
                           "— no service from this context", context.get("name"), res.cause)
            return []
        return [s for s in res.payload.get("services", []) if isinstance(s, dict)]

    results = await asyncio.gather(*[_one(c) for c in named])
    merged: list[dict] = []
    for services in results:
        merged.extend(services)

    if not merged:
        return EnrichmentResult(
            payload={}, ok=False,
            cause="no output (turn cap / parse / api error): no service produced for "
                  "any bounded context")
    return EnrichmentResult(payload={"services": merged}, ok=True, cause=None)
