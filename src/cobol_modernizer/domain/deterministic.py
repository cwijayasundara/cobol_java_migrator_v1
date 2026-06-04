from __future__ import annotations

import json
import re
from typing import Any

from cobol_modernizer.domain.schema import (
    Aggregate,
    BoundedContextDecl,
    CobolMapping,
    ContextDependency,
    ContextDesign,
    DecompositionMap,
    DomainDesign,
    TopologyDecision,
)


_WRITES_BY_PROGRAM = """
MATCH (p:CodeEntity {repo:$repo}) WHERE p.kind = 'Program'
OPTIONAL MATCH (p)-[w:WRITES]->(x:CodeEntity)
RETURN p.qualified_name AS program,
       collect(DISTINCT coalesce(w.resource, x.simple_name, x.qualified_name)) AS writes
"""
_KNOWN_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"


def _slug(value: str, fallback: str = "Context") -> str:
    words = re.split(r"[^A-Za-z0-9]+", value)
    out = "".join(w[:1].upper() + w[1:] for w in words if w)
    return out or fallback


def _method(value: str, fallback: str) -> str:
    name = _slug(value, fallback)
    return name[:1].lower() + name[1:]


def _load_backlog(backlog_json: str) -> dict[str, Any]:
    try:
        data = json.loads(backlog_json or "{}")
    except json.JSONDecodeError:
        return {"epics": [], "stories": []}
    if not isinstance(data, dict):
        return {"epics": [], "stories": []}
    return {
        "epics": [e for e in data.get("epics", []) if isinstance(e, dict)],
        "stories": [s for s in data.get("stories", []) if isinstance(s, dict)],
    }


def _writers(client: Any, repo_slug: str) -> dict[str, list[str]]:
    rows = client.run(_WRITES_BY_PROGRAM, repo=repo_slug)
    out: dict[str, list[str]] = {}
    for row in rows:
        program = row.get("program")
        if program:
            out[str(program)] = sorted({str(w) for w in (row.get("writes") or []) if w})
    return out


def _known_refs(client: Any, repo_slug: str) -> set[str]:
    return {str(r["q"]) for r in client.run(_KNOWN_REFS_Q, repo=repo_slug) if r.get("q")}


def _story_refs(story: dict) -> set[str]:
    refs = set(str(r) for r in (story.get("evidence_refs") or []) if r)
    for refs_list in (story.get("evidence_map") or {}).values():
        refs.update(str(r) for r in (refs_list or []) if r)
    return refs


def _group_stories(backlog: dict[str, Any]) -> list[tuple[str, dict | None, list[dict]]]:
    stories = backlog.get("stories") or []
    epics = backlog.get("epics") or []
    if epics:
        groups: list[tuple[str, dict | None, list[dict]]] = []
        for epic in epics:
            eid = str(epic.get("id", ""))
            owned = [s for s in stories if str(s.get("epic_id", "")) == eid]
            if owned:
                groups.append((eid, epic, owned))
        orphans = [s for s in stories if not any(s in g[2] for g in groups)]
        if orphans:
            groups.append(("coverage", {"title": "Coverage"}, orphans))
        return groups
    by_epic: dict[str, list[dict]] = {}
    for story in stories:
        key = str(story.get("epic_id") or "Capability")
        by_epic.setdefault(key, []).append(story)
    return [(key, {"title": key}, value) for key, value in by_epic.items()]


def generate_deterministic_domain_design(
    client: Any,
    repo_slug: str,
    *,
    brd_text: str,
    backlog_json: str = "",
    version: int = 0,
) -> DomainDesign:
    """Derive a macro-first DDD design from BRD/backlog/graph facts without LLM calls."""
    _ = brd_text
    backlog = _load_backlog(backlog_json)
    writers = _writers(client, repo_slug)
    known_refs = _known_refs(client, repo_slug)
    groups = _group_stories(backlog)
    if not groups:
        groups = [
            (program, {"title": program}, [{
                "id": f"US-{_slug(program)}",
                "title": f"Modernize {program}",
                "evidence_refs": [program],
            }])
            for program in sorted(writers)
        ]

    unassigned = set(writers)
    contexts: list[BoundedContextDecl] = []
    designs: list[ContextDesign] = []
    for idx, (_key, epic, stories) in enumerate(groups, start=1):
        title = str((epic or {}).get("title") or (epic or {}).get("outcome") or f"Capability {idx}")
        ctx_name = _slug(title, f"Context{idx}")
        refs = sorted({r for story in stories for r in _story_refs(story)})
        member_programs = sorted([r for r in refs if r in writers])
        if not member_programs and unassigned:
            member_programs = [sorted(unassigned)[0]]
        for program in member_programs:
            unassigned.discard(program)
        owned = sorted({res for program in member_programs for res in writers.get(program, [])})
        cited = sorted(set(member_programs) | (set(refs) & known_refs))
        aggregate_name = _slug(title, "Capability")
        methods = sorted({
            _method(str(story.get("title") or story.get("id") or "execute"), f"execute{idx}")
            for story in stories
        })
        if not methods:
            methods = [f"execute{aggregate_name}"]
        aggregate = Aggregate(
            name=aggregate_name,
            root_entity=aggregate_name,
            invariants=[
                f"{aggregate_name} enforces BRD-backed business rules before state changes",
                f"{aggregate_name} owns writes to {', '.join(owned) if owned else 'its state'}",
            ],
            entities=owned or [aggregate_name],
            value_objects=["LegacyReference"],
            methods=methods,
        )
        repositories = [f"{_slug(res)}Repository" for res in owned] or [f"{aggregate_name}Repository"]
        events = [f"{_slug(method)}Completed" for method in methods[:3]]
        api = "; ".join(f"POST /{ctx_name[:1].lower() + ctx_name[1:]}/{m}" for m in methods[:4])
        mapping_refs = member_programs or cited
        design = ContextDesign(
            context=ctx_name,
            aggregates=[aggregate],
            value_objects=["LegacyReference"],
            domain_services=[f"{ctx_name}Service"],
            repositories=repositories,
            domain_events=events,
            api_surface=api,
            cobol_mapping=[
                CobolMapping(cobol_ref=ref, maps_to=f"{aggregate.name}.{methods[0]}",
                             note="Legacy behavior folded into the macro capability aggregate")
                for ref in mapping_refs
            ],
            cited_refs=cited,
        )
        contexts.append(BoundedContextDecl(
            name=ctx_name,
            business_capability=title,
            member_programs=member_programs,
            owned_resources=owned,
            depends_on=[],
            topology=TopologyDecision(
                deployment="microservice" if owned else "module",
                score=0.82 if owned else 0.55,
                inputs={"macro_first": 1.0, "owned_resource_count": float(len(owned))},
                rationale=("macro-first vertical capability with owned data"
                           if owned else "module until owned data boundary is clear"),
            ),
            extraction_rank=idx,
            identity_drift=False,
            cited_refs=cited,
        ))
        designs.append(design)

    # Keep any writer not evidenced by backlog visible instead of silently dropping it.
    for program in sorted(unassigned):
        ctx_name = _slug(program)
        owned = writers.get(program, [])
        aggregate = Aggregate(
            name=ctx_name, root_entity=ctx_name,
            invariants=[f"{ctx_name} owns writes to {', '.join(owned) or program}"],
            entities=owned or [ctx_name], value_objects=["LegacyReference"],
            methods=[f"execute{ctx_name}"])
        contexts.append(BoundedContextDecl(
            name=ctx_name, business_capability=f"Modernize {program}",
            member_programs=[program], owned_resources=owned, cited_refs=[program],
            topology=TopologyDecision(
                deployment="microservice" if owned else "module", score=0.7,
                inputs={"unassigned_writer": 1.0},
                rationale="coverage context for writer not represented in backlog"),
            extraction_rank=len(contexts) + 1))
        designs.append(ContextDesign(
            context=ctx_name, aggregates=[aggregate], value_objects=["LegacyReference"],
            domain_services=[f"{ctx_name}Service"],
            repositories=[f"{_slug(res)}Repository" for res in owned] or [f"{ctx_name}Repository"],
            domain_events=[f"{ctx_name}Completed"],
            api_surface=f"POST /{ctx_name[:1].lower() + ctx_name[1:]}/execute",
            cobol_mapping=[CobolMapping(cobol_ref=program, maps_to=f"{ctx_name}.execute{ctx_name}")],
            cited_refs=[program]))

    cited_refs = sorted({ref for ctx in contexts for ref in ctx.cited_refs})
    return DomainDesign(
        repo_slug=repo_slug, version=version, rating="high", weighted_score=1.0,
        contexts=contexts, designs=designs, cited_refs=cited_refs)
