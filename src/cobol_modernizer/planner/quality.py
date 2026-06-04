from __future__ import annotations

from typing import Any

from cobol_modernizer.planner.schema import StoryDAG


def assess_plan_quality(
    dag: StoryDAG,
    *,
    seam_candidates: list[dict],
    acyclic: bool,
    topo_order: list[str],
    delivery_waves: list[list[str]],
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    seam_programs = {str(c.get("program")) for c in seam_candidates if c.get("program")}
    story_ids = [s.id for s in dag.stories]
    duplicate_story_ids = sorted({sid for sid in story_ids if story_ids.count(sid) > 1})
    story_id_set = set(story_ids)
    unknown_dependency_ids = sorted({
        dep for story in dag.stories for dep in story.depends_on if dep not in story_id_set
    })
    stories_without_seam = sorted(s.id for s in dag.stories if not s.seam)
    stories_with_unknown_seam = sorted(
        s.id for s in dag.stories if s.seam and s.seam not in seam_programs
    )
    stories_without_evidence = sorted(
        s.id for s in dag.stories if not any((s.evidence_map or {}).values())
    )
    wave_ids = [sid for wave in delivery_waves for sid in wave]
    missing_from_waves = sorted(story_id_set - set(wave_ids))
    unknown_wave_story_ids = sorted(set(wave_ids) - story_id_set)

    result = {
        "story_count": len(dag.stories),
        "seam_count": len(seam_programs),
        "acyclic": acyclic,
        "topo_order_count": len(topo_order),
        "delivery_wave_count": len(delivery_waves),
        "duplicate_story_ids": duplicate_story_ids,
        "unknown_dependency_ids": unknown_dependency_ids,
        "stories_without_seam": stories_without_seam,
        "stories_with_unknown_seam": stories_with_unknown_seam,
        "stories_without_evidence": stories_without_evidence,
        "missing_from_waves": missing_from_waves,
        "unknown_wave_story_ids": unknown_wave_story_ids,
    }
    threshold = {
        "require_acyclic": True,
        "min_stories": 1,
        "require_topo_order_covers_all_stories": True,
        "require_delivery_waves_cover_all_stories": True,
        "require_story_evidence": True,
        "allow_unknown_seams": False,
        "allow_unknown_dependencies": False,
    }
    passed = (
        acyclic
        and len(dag.stories) >= 1
        and len(topo_order) == len(dag.stories)
        and len(wave_ids) == len(dag.stories)
        and not duplicate_story_ids
        and not unknown_dependency_ids
        and not stories_without_seam
        and not stories_with_unknown_seam
        and not stories_without_evidence
        and not missing_from_waves
        and not unknown_wave_story_ids
    )
    return passed, result, threshold
