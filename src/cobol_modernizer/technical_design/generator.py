"""DDD contexts + backlog stories + seam waves → target technical architecture
(services with API/persistence/integration contracts), grounded on graph refs, known
story ids, and known DDD context names. Parser drops anything ungrounded."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from cobol_modernizer.enrichment.base import run_batched
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
