from __future__ import annotations

from cobol_modernizer.technical_design.schema import TechnicalDesign


def assess_technical_design_quality(
    design: TechnicalDesign,
    *,
    known_contexts: set[str],
    known_story_ids: set[str],
) -> tuple[bool, dict, dict]:
    services = design.services
    service_names = [s.name for s in services]
    contexts = [s.bounded_context for s in services]
    duplicate_services = sorted({n for n in service_names if service_names.count(n) > 1})
    missing_contexts = sorted(known_contexts.difference(contexts))
    unknown_contexts = sorted(set(contexts).difference(known_contexts))
    services_without_api = sorted(s.name for s in services if not s.api_contracts)
    services_without_stories = sorted(
        s.name for s in services if known_story_ids and not s.story_ids)
    non_microservices = sorted(s.name for s in services if s.deployment != "microservice")
    services_without_packages = sorted(
        s.name for s in services
        if not any(s.name.replace("-service", "").replace("-", "") in p
                   for p in design.package_structure)
    )
    services_without_db_design = sorted(
        s.name for s in services
        if not any(isinstance(d, dict) and d.get("service") == s.name
                   for d in design.database_design)
    )
    story_refs = {story_id for s in services for story_id in s.story_ids}
    unknown_story_ids = sorted(story_refs.difference(known_story_ids))

    owners: dict[str, list[str]] = {}
    for svc in services:
        for item in svc.persistence:
            owners.setdefault(item.resource, []).append(svc.name)
    multi_owner_resources = sorted(
        resource for resource, resource_owners in owners.items()
        if len(set(resource_owners)) > 1)

    result = {
        "service_count": len(services),
        "context_count": len(known_contexts),
        "story_count": len(known_story_ids),
        "target_platform": design.target_platform,
        "has_spring_boot_4": str(design.target_platform.get("spring_boot_version", "")).startswith("4."),
        "has_package_structure": bool(design.package_structure),
        "has_database_design": bool(design.database_design),
        "has_mermaid_component_diagram": bool(design.mermaid_component_diagram.strip()),
        "duplicate_services": duplicate_services,
        "missing_contexts": missing_contexts,
        "unknown_contexts": unknown_contexts,
        "unknown_story_ids": unknown_story_ids,
        "services_without_api": services_without_api,
        "services_without_stories": services_without_stories,
        "non_microservices": non_microservices,
        "services_without_packages": services_without_packages,
        "services_without_db_design": services_without_db_design,
        "multi_owner_resources": multi_owner_resources,
    }
    threshold = {
        "minimum_services": max(1, len(known_contexts)),
        "spring_boot_major": 4,
        "missing_contexts": 0,
        "unknown_contexts": 0,
        "unknown_story_ids": 0,
        "services_without_api": 0,
        "non_microservices": 0,
        "multi_owner_resources": 0,
        "package_structure_required": True,
        "database_design_required": True,
        "mermaid_component_diagram_required": True,
    }
    passed = (
        len(services) >= threshold["minimum_services"]
        and result["has_spring_boot_4"]
        and result["has_package_structure"]
        and result["has_database_design"]
        and result["has_mermaid_component_diagram"]
        and not duplicate_services
        and not missing_contexts
        and not unknown_contexts
        and not unknown_story_ids
        and not services_without_api
        and not non_microservices
        and not multi_owner_resources
    )
    return passed, result, threshold
