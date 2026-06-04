from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.domain.schema import DomainDesign


def _load_backlog(backlog_json: str) -> dict[str, Any]:
    try:
        data = json.loads(backlog_json or "{}")
    except json.JSONDecodeError:
        return {"stories": []}
    return data if isinstance(data, dict) else {"stories": []}


def assess_domain_quality(
    design: DomainDesign,
    *,
    known_refs: set[str],
    backlog_json: str = "",
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    backlog = _load_backlog(backlog_json)
    story_ids = sorted(str(s.get("id")) for s in backlog.get("stories", []) if s.get("id"))
    context_names = {c.name for c in design.contexts}
    design_context_names = {d.context for d in design.designs}
    duplicate_contexts = sorted({
        c.name for c in design.contexts if [x.name for x in design.contexts].count(c.name) > 1
    })
    missing_designs = sorted(context_names - design_context_names)
    orphan_designs = sorted(design_context_names - context_names)
    contexts_without_programs = sorted(c.name for c in design.contexts if not c.member_programs)
    contexts_without_capability = sorted(c.name for c in design.contexts if not c.business_capability)
    resources: dict[str, list[str]] = {}
    for c in design.contexts:
        for res in c.owned_resources:
            resources.setdefault(res, []).append(c.name)
    multi_owner_resources = {
        res: sorted(owners) for res, owners in resources.items() if len(set(owners)) > 1
    }
    anemic_aggregates = sorted(
        f"{d.context}.{a.name}"
        for d in design.designs
        for a in d.aggregates
        if not a.invariants or not a.methods
    )
    designs_without_api = sorted(d.context for d in design.designs if not d.api_surface)
    designs_without_repositories = sorted(d.context for d in design.designs if not d.repositories)
    designs_without_mapping = sorted(d.context for d in design.designs if not d.cobol_mapping)
    unknown_refs = sorted({
        ref
        for ref in (
            [r for c in design.contexts for r in c.cited_refs + c.member_programs]
            + [r for d in design.designs for r in d.cited_refs]
            + [m.cobol_ref for d in design.designs for m in d.cobol_mapping]
        )
        if ref and ref not in known_refs
    })
    result = {
        "context_count": len(design.contexts),
        "design_count": len(design.designs),
        "story_count": len(story_ids),
        "duplicate_contexts": duplicate_contexts,
        "missing_designs": missing_designs,
        "orphan_designs": orphan_designs,
        "contexts_without_programs": contexts_without_programs,
        "contexts_without_capability": contexts_without_capability,
        "multi_owner_resources": multi_owner_resources,
        "anemic_aggregates": anemic_aggregates,
        "designs_without_api": designs_without_api,
        "designs_without_repositories": designs_without_repositories,
        "designs_without_mapping": designs_without_mapping,
        "unknown_refs": unknown_refs,
    }
    threshold = {
        "min_contexts": 1,
        "require_one_design_per_context": True,
        "require_program_membership": True,
        "require_owned_resource_single_owner": True,
        "require_non_anemic_aggregates": True,
        "require_api_repository_mapping": True,
        "allow_unknown_refs": False,
    }
    passed = (
        len(design.contexts) >= 1
        and not duplicate_contexts
        and not missing_designs
        and not orphan_designs
        and not contexts_without_programs
        and not contexts_without_capability
        and not multi_owner_resources
        and not anemic_aggregates
        and not designs_without_api
        and not designs_without_repositories
        and not designs_without_mapping
        and not unknown_refs
    )
    return passed, result, threshold
