"""Phase 2: one focused agent PER context produces the full DDD tactical design
(aggregates/entities/value-objects/domain-services/repositories/events/API + the
COBOL->domain mapping). Small bounded jobs => deep output, parallelizable, no turn-cap
starvation. Groundedness is enforced on the returned refs."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from cobol_modernizer.domain.schema import (
    CONTEXT_DESIGN_SCHEMA, Aggregate, BoundedContextDecl, CobolMapping, ContextDesign,
)
from cobol_modernizer.enrichment.base import ground_refs, run_batched
from cobol_modernizer.enrichment.base import run_batched_result

TACTICAL_SYSTEM = (
    "You design the OO domain model for ONE bounded context of a Spring Boot system rebuilt "
    "from legacy COBOL. Produce RICH aggregates: fold COBOL paragraph behavior into aggregate "
    "methods and protect invariants — do NOT emit anemic CRUD classes that merely mirror copybook "
    "fields. For the context's owned resources, define aggregates, entities, value objects, domain "
    "services, repository interfaces, domain events, and a REST/command API surface. Provide a "
    "cobol_mapping: each entry maps a COBOL copybook/record/paragraph qualified-name to the domain "
    "element it becomes. Ground everything ONLY in this context's member programs/resources; cite "
    "refs in cited_refs; invent no identifiers. "
    'Return JSON: {"aggregates":[{"name","root_entity","invariants":[str],"entities":[str],'
    '"value_objects":[str],"methods":[str]}],"value_objects":[str],"domain_services":[str],'
    '"repositories":[str],"domain_events":[str],"api_surface","cobol_mapping":[{"cobol_ref",'
    '"maps_to","note"}],"cited_refs":[str]}.'
)

AGGREGATE_SYSTEM = (
    "You design ONLY the aggregate model for ONE bounded context of a Spring Boot "
    "system rebuilt from legacy COBOL. Produce rich aggregate roots, entities, value "
    "objects, invariants, methods, and domain services. Do not design repositories, "
    "events, APIs, or COBOL mappings in this unit. Ground everything in the provided "
    "context refs; invent no identifiers."
)

CONTRACT_SYSTEM = (
    "You design ONLY the tactical contracts for ONE bounded context: repository "
    "interfaces, domain events, and REST/command API surface. Use the provided "
    "aggregate model as context. Do not emit aggregates or COBOL mappings. Ground "
    "everything in the provided context refs; invent no identifiers."
)

MAPPING_SYSTEM = (
    "You design ONLY the COBOL-to-domain mapping for ONE bounded context. Map COBOL "
    "copybook/record/paragraph qualified-names to aggregate methods, value objects, "
    "repositories, or API operations from the provided aggregate/contract design. "
    "Do not emit aggregates or APIs. Ground every mapping in known context refs; "
    "invent no identifiers."
)

AGGREGATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "aggregates": CONTEXT_DESIGN_SCHEMA["properties"]["aggregates"],
        "value_objects": CONTEXT_DESIGN_SCHEMA["properties"]["value_objects"],
        "domain_services": CONTEXT_DESIGN_SCHEMA["properties"]["domain_services"],
        "cited_refs": CONTEXT_DESIGN_SCHEMA["properties"]["cited_refs"],
    },
    "required": ["aggregates"],
}

CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repositories": CONTEXT_DESIGN_SCHEMA["properties"]["repositories"],
        "domain_events": CONTEXT_DESIGN_SCHEMA["properties"]["domain_events"],
        "api_surface": CONTEXT_DESIGN_SCHEMA["properties"]["api_surface"],
        "cited_refs": CONTEXT_DESIGN_SCHEMA["properties"]["cited_refs"],
    },
    "required": ["repositories"],
}

MAPPING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cobol_mapping": CONTEXT_DESIGN_SCHEMA["properties"]["cobol_mapping"],
        "cited_refs": CONTEXT_DESIGN_SCHEMA["properties"]["cited_refs"],
    },
    "required": ["cobol_mapping"],
}


def _parse(raw: dict, ctx: BoundedContextDecl, known_refs: set[str]) -> ContextDesign:
    aggs = []
    for a in raw.get("aggregates", []):
        if isinstance(a, dict) and isinstance(a.get("name"), str):
            aggs.append(Aggregate(
                name=a["name"], root_entity=str(a.get("root_entity", a["name"])),
                invariants=[s for s in (a.get("invariants") or []) if isinstance(s, str)],
                entities=[s for s in (a.get("entities") or []) if isinstance(s, str)],
                value_objects=[s for s in (a.get("value_objects") or []) if isinstance(s, str)],
                methods=[s for s in (a.get("methods") or []) if isinstance(s, str)]))
    maps = [CobolMapping(cobol_ref=m["cobol_ref"], maps_to=m["maps_to"],
                         note=str(m.get("note", "")))
            for m in raw.get("cobol_mapping", [])
            if isinstance(m, dict) and m.get("cobol_ref") and m.get("maps_to")]
    cited, _ok = ground_refs(raw.get("cited_refs"), known_refs)
    return ContextDesign(
        context=ctx.name, aggregates=aggs,
        value_objects=[s for s in (raw.get("value_objects") or []) if isinstance(s, str)],
        domain_services=[s for s in (raw.get("domain_services") or []) if isinstance(s, str)],
        repositories=[s for s in (raw.get("repositories") or []) if isinstance(s, str)],
        domain_events=[s for s in (raw.get("domain_events") or []) if isinstance(s, str)],
        api_surface=str(raw.get("api_surface", "")), cobol_mapping=maps, cited_refs=cited)


async def design_context(ctx: BoundedContextDecl, *, known_refs: set[str], runner: Any,
                         model: str, timeout_s: float) -> ContextDesign:
    prompt = ("## Bounded context\n```json\n"
              + json.dumps(ctx.model_dump(mode="json")) + "\n```\n"
              "Design the full DDD tactical model for THIS context only.")
    raw = await run_batched(runner=runner, system=TACTICAL_SYSTEM, prompt=prompt,
                            schema=CONTEXT_DESIGN_SCHEMA, model=model, timeout_s=timeout_s,
                            label=f"domain-tactical:{ctx.name}")
    return _parse(raw, ctx, known_refs)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _merge_raw_parts(*, aggregate: dict, contract: dict, mapping: dict) -> dict:
    cited: list[str] = []
    for part in (aggregate, contract, mapping):
        for ref in part.get("cited_refs", []) or []:
            if isinstance(ref, str) and ref not in cited:
                cited.append(ref)
    return {
        "aggregates": aggregate.get("aggregates", []),
        "value_objects": aggregate.get("value_objects", []),
        "domain_services": aggregate.get("domain_services", []),
        "repositories": contract.get("repositories", []),
        "domain_events": contract.get("domain_events", []),
        "api_surface": contract.get("api_surface", ""),
        "cobol_mapping": mapping.get("cobol_mapping", []),
        "cited_refs": cited,
    }


async def generate_aggregate_payload(ctx: BoundedContextDecl, *, runner: Any,
                                     model: str, timeout_s: float,
                                     attempts: int | None = None,
                                     max_turns: int | None = None) -> dict:
    attempts = max(1, attempts if attempts is not None
                   else _env_int("DOMAIN_TACTICAL_UNIT_ATTEMPTS", 2))
    max_turns = max(1, max_turns if max_turns is not None
                    else _env_int("DOMAIN_TACTICAL_UNIT_MAX_TURNS", 4))
    ctx_json = json.dumps(ctx.model_dump(mode="json"))
    prompt = (
        "## Bounded context\n```json\n" + ctx_json + "\n```\n"
        "Design only the aggregate model for this context.")
    result = await run_batched_result(
        runner=runner, system=AGGREGATE_SYSTEM, prompt=prompt,
        schema=AGGREGATE_SCHEMA, model=model, timeout_s=timeout_s,
        label=f"domain-aggregate:{ctx.name}", max_turns=max_turns,
        attempts=attempts, escalate=True)
    if not result.ok:
        raise ValueError(f"domain aggregate {ctx.name}: {result.cause}")
    return result.payload


async def generate_contract_payload(ctx: BoundedContextDecl, *, aggregate_payload: dict,
                                    runner: Any, model: str, timeout_s: float,
                                    attempts: int | None = None,
                                    max_turns: int | None = None) -> dict:
    attempts = max(1, attempts if attempts is not None
                   else _env_int("DOMAIN_TACTICAL_UNIT_ATTEMPTS", 2))
    max_turns = max(1, max_turns if max_turns is not None
                    else _env_int("DOMAIN_TACTICAL_UNIT_MAX_TURNS", 4))
    ctx_json = json.dumps(ctx.model_dump(mode="json"))
    prompt = (
        "## Bounded context\n```json\n" + ctx_json + "\n```\n"
        "## Aggregate model\n```json\n" + json.dumps(aggregate_payload) + "\n```\n"
        "Design only repositories, domain events, and API surface for this context.")
    result = await run_batched_result(
        runner=runner, system=CONTRACT_SYSTEM, prompt=prompt,
        schema=CONTRACT_SCHEMA, model=model, timeout_s=timeout_s,
        label=f"domain-contract:{ctx.name}", max_turns=max_turns,
        attempts=attempts, escalate=True)
    if not result.ok:
        raise ValueError(f"domain contract {ctx.name}: {result.cause}")
    return result.payload


async def generate_mapping_payload(ctx: BoundedContextDecl, *,
                                   aggregate_payload: dict, contract_payload: dict,
                                   runner: Any, model: str, timeout_s: float,
                                   attempts: int | None = None,
                                   max_turns: int | None = None) -> dict:
    attempts = max(1, attempts if attempts is not None
                   else _env_int("DOMAIN_TACTICAL_UNIT_ATTEMPTS", 2))
    max_turns = max(1, max_turns if max_turns is not None
                    else _env_int("DOMAIN_TACTICAL_UNIT_MAX_TURNS", 4))
    ctx_json = json.dumps(ctx.model_dump(mode="json"))
    prompt = (
        "## Bounded context\n```json\n" + ctx_json + "\n```\n"
        "## Aggregate model\n```json\n" + json.dumps(aggregate_payload) + "\n```\n"
        "## Tactical contracts\n```json\n" + json.dumps(contract_payload) + "\n```\n"
        "Design only the COBOL-to-domain mapping for this context.")
    result = await run_batched_result(
        runner=runner, system=MAPPING_SYSTEM, prompt=prompt,
        schema=MAPPING_SCHEMA, model=model, timeout_s=timeout_s,
        label=f"domain-mapping:{ctx.name}", max_turns=max_turns,
        attempts=attempts, escalate=True)
    if not result.ok:
        raise ValueError(f"domain mapping {ctx.name}: {result.cause}")
    return result.payload


async def design_context_decomposed(ctx: BoundedContextDecl, *, known_refs: set[str],
                                    runner: Any, model: str,
                                    timeout_s: float) -> ContextDesign:
    """Generate one context design as three smaller structured units.

    This is the production path for ledger-backed Domain Design runs. It keeps the
    public `ContextDesign` output unchanged while avoiding one broad tactical prompt
    that has to produce aggregates, contracts, API, events, and COBOL mapping at once.
    """
    aggregate = await generate_aggregate_payload(ctx, runner=runner, model=model,
                                                 timeout_s=timeout_s)
    contract = await generate_contract_payload(
        ctx, aggregate_payload=aggregate, runner=runner, model=model,
        timeout_s=timeout_s)
    mapping = await generate_mapping_payload(
        ctx, aggregate_payload=aggregate, contract_payload=contract,
        runner=runner, model=model, timeout_s=timeout_s)
    raw = _merge_raw_parts(aggregate=aggregate, contract=contract, mapping=mapping)
    return _parse(raw, ctx, known_refs)


async def design_all_contexts(contexts: list[BoundedContextDecl], *, known_refs: set[str],
                              runner: Any, model: str, timeout_s: float) -> list[ContextDesign]:
    tasks = [design_context(c, known_refs=known_refs, runner=runner, model=model,
                            timeout_s=timeout_s) for c in contexts]
    return list(await asyncio.gather(*tasks))
