"""Phase 2: one focused agent PER context produces the full DDD tactical design
(aggregates/entities/value-objects/domain-services/repositories/events/API + the
COBOL->domain mapping). Small bounded jobs => deep output, parallelizable, no turn-cap
starvation. Groundedness is enforced on the returned refs."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from cobol_modernizer.domain.schema import (
    CONTEXT_DESIGN_SCHEMA, Aggregate, BoundedContextDecl, CobolMapping, ContextDesign,
)
from cobol_modernizer.enrichment.base import ground_refs, run_batched

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


async def design_all_contexts(contexts: list[BoundedContextDecl], *, known_refs: set[str],
                              runner: Any, model: str, timeout_s: float) -> list[ContextDesign]:
    tasks = [design_context(c, known_refs=known_refs, runner=runner, model=model,
                            timeout_s=timeout_s) for c in contexts]
    return list(await asyncio.gather(*tasks))
