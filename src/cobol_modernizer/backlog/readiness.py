from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cobol_modernizer.backlog.schema import Backlog


def _requirement_ids(brd_sections: list[dict]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for sec in brd_sections:
        if not isinstance(sec, dict):
            continue
        for req in sec.get("requirements", []) or []:
            if not isinstance(req, dict):
                continue
            rid = str(req.get("id", "")).strip()
            if rid and rid not in seen:
                seen.add(rid)
                out.append(rid)
    return out


def _unknown_refs(values: Iterable[str], known_refs: set[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in known_refs and value not in out:
            out.append(value)
    return out


def assess_backlog_readiness(
    backlog: Backlog,
    *,
    brd_sections: list[dict],
    known_refs: set[str],
    graph_coverage_ratio: float,
    min_graph_coverage: float,
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    """Deterministically decide if a backlog is usable for downstream blueprint work."""
    expected_req_ids = set(_requirement_ids(brd_sections))
    covered_req_ids = {
        rid
        for story in backlog.stories
        for rid in story.brd_requirement_ids
        if rid
    }
    story_ids = [story.id for story in backlog.stories]
    epic_ids = {epic.id for epic in backlog.epics}
    known_story_ids = set(story_ids)

    duplicate_story_ids = sorted({
        sid for sid in story_ids if story_ids.count(sid) > 1
    })
    missing_requirement_ids = sorted(expected_req_ids - covered_req_ids)
    unknown_requirement_ids = sorted(covered_req_ids - expected_req_ids)
    orphan_story_ids = sorted(
        story.id for story in backlog.stories if story.epic_id not in epic_ids
    )
    stories_without_requirements = sorted(
        story.id for story in backlog.stories if not story.brd_requirement_ids
    )
    stories_without_evidence = sorted(
        story.id for story in backlog.stories if not story.evidence_refs
    )
    stories_without_acceptance_criteria = sorted(
        story.id for story in backlog.stories if not story.acceptance_criteria
    )
    ac_without_evidence = sorted(
        ac.id
        for story in backlog.stories
        for ac in story.acceptance_criteria
        if not ac.evidence_refs
    )
    epic_story_refs_missing = sorted({
        sid
        for epic in backlog.epics
        for sid in epic.story_ids
        if sid and sid not in known_story_ids
    })

    unknown_evidence_refs: list[str] = []
    for epic in backlog.epics:
        unknown_evidence_refs.extend(_unknown_refs(epic.evidence_refs, known_refs))
    for story in backlog.stories:
        unknown_evidence_refs.extend(_unknown_refs(story.evidence_refs, known_refs))
        unknown_evidence_refs.extend(_unknown_refs(story.seam_refs, known_refs))
        for ac in story.acceptance_criteria:
            unknown_evidence_refs.extend(_unknown_refs(ac.evidence_refs, known_refs))
    unknown_evidence_refs = sorted(set(unknown_evidence_refs))

    req_coverage_ratio = (
        len(covered_req_ids & expected_req_ids) / len(expected_req_ids)
        if expected_req_ids else 1.0
    )
    result = {
        "requirement_coverage_ratio": req_coverage_ratio,
        "graph_coverage_ratio": graph_coverage_ratio,
        "epics": len(backlog.epics),
        "stories": len(backlog.stories),
        "expected_requirement_ids": sorted(expected_req_ids),
        "covered_requirement_ids": sorted(covered_req_ids & expected_req_ids),
        "missing_requirement_ids": missing_requirement_ids,
        "unknown_requirement_ids": unknown_requirement_ids,
        "duplicate_story_ids": duplicate_story_ids,
        "orphan_story_ids": orphan_story_ids,
        "stories_without_requirements": stories_without_requirements,
        "stories_without_evidence": stories_without_evidence,
        "stories_without_acceptance_criteria": stories_without_acceptance_criteria,
        "acceptance_criteria_without_evidence": ac_without_evidence,
        "epic_story_refs_missing": epic_story_refs_missing,
        "unknown_evidence_refs": unknown_evidence_refs,
    }
    threshold = {
        "min_requirement_coverage": 1.0,
        "min_graph_coverage": min_graph_coverage,
        "allow_duplicate_story_ids": False,
        "allow_orphan_stories": False,
        "require_story_requirements": True,
        "require_story_evidence": True,
        "require_acceptance_criteria": True,
        "require_acceptance_criteria_evidence": True,
        "allow_unknown_refs": False,
    }
    passed = (
        req_coverage_ratio >= 1.0
        and graph_coverage_ratio >= min_graph_coverage
        and not missing_requirement_ids
        and not unknown_requirement_ids
        and not duplicate_story_ids
        and not orphan_story_ids
        and not stories_without_requirements
        and not stories_without_evidence
        and not stories_without_acceptance_criteria
        and not ac_without_evidence
        and not epic_story_refs_missing
        and not unknown_evidence_refs
    )
    return passed, result, threshold
